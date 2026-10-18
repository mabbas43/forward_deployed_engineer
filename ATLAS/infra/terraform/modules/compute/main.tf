variable "env" { type = string }
variable "region" { type = string }
variable "image" { type = string }
variable "vpc_id" { type = string }
variable "public_subnet_ids" { type = list(string) }
variable "private_subnet_ids" { type = list(string) }
variable "app_sg_id" { type = string }
variable "queue_url" { type = string }
variable "queue_arn" { type = string }
variable "queue_name" { type = string }
variable "db_secret_arn" { type = string }
variable "redis_endpoint" { type = string }
variable "worker_min" { type = number }
variable "worker_max" { type = number }
variable "canary_weight" { type = number }

resource "aws_ecs_cluster" "this" {
  name = "atlas-${var.env}"
  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

resource "aws_cloudwatch_log_group" "app" {
  name              = "/atlas/${var.env}"
  retention_in_days = 30
}

data "aws_iam_policy_document" "assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "task" {
  name               = "atlas-${var.env}-task"
  assume_role_policy = data.aws_iam_policy_document.assume.json
}

resource "aws_iam_role_policy" "task" {
  role = aws_iam_role.task.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["sqs:SendMessage", "sqs:ReceiveMessage", "sqs:DeleteMessage",
      "sqs:ChangeMessageVisibility", "sqs:GetQueueAttributes"], Resource = var.queue_arn },
      { Effect = "Allow", Action = ["secretsmanager:GetSecretValue"], Resource = "*" },
    ]
  })
}

resource "aws_iam_role" "exec" {
  name               = "atlas-${var.env}-exec"
  assume_role_policy = data.aws_iam_policy_document.assume.json
}

resource "aws_iam_role_policy_attachment" "exec" {
  role       = aws_iam_role.exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

locals {
  env_vars = [
    { name = "QUEUE_URL", value = var.queue_url },
    { name = "REDIS_URL", value = "rediss://${var.redis_endpoint}:6379/0" },
    { name = "AWS_DEFAULT_REGION", value = var.region },
    { name = "ATLAS_ENV", value = var.env },
  ]
  services = {
    api         = { command = null, cpu = 512, memory = 1024, port = 8000 }
    worker      = { command = ["uv", "run", "--no-sync", "python", "-m", "atlas.api.worker"], cpu = 1024, memory = 2048, port = null }
    mcp-it      = { command = ["uv", "run", "--no-sync", "python", "-m", "atlas.mcp.it_server"], cpu = 256, memory = 512, port = 8001 }
    online-eval = { command = ["uv", "run", "--no-sync", "python", "-m", "atlas.ops.online_eval"], cpu = 256, memory = 512, port = null }
  }
}

resource "aws_ecs_task_definition" "svc" {
  for_each                 = local.services
  family                   = "atlas-${var.env}-${each.key}"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = each.value.cpu
  memory                   = each.value.memory
  task_role_arn            = aws_iam_role.task.arn
  execution_role_arn       = aws_iam_role.exec.arn
  container_definitions = jsonencode([{
    name         = each.key
    image        = var.image
    command      = each.value.command
    environment  = local.env_vars
    portMappings = each.value.port == null ? [] : [{ containerPort = each.value.port }]
    logConfiguration = { logDriver = "awslogs", options = {
      awslogs-group = aws_cloudwatch_log_group.app.name, awslogs-region = var.region, awslogs-stream-prefix = each.key
    } }
  }])
}

resource "aws_lb" "api" {
  name               = "atlas-${var.env}"
  load_balancer_type = "application"
  subnets            = var.public_subnet_ids
  security_groups    = [var.app_sg_id]
}

resource "aws_lb_target_group" "api" {
  for_each    = toset(["stable", "canary"])
  name        = "atlas-${var.env}-${each.key}"
  port        = 8000
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip"
  health_check { path = "/healthz" }
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.api.arn
  port              = 80
  protocol          = "HTTP" # terminate TLS with ACM (HTTPS:443) in prod
  default_action {
    type = "forward"
    forward {
      target_group {
        arn    = aws_lb_target_group.api["stable"].arn
        weight = 100 - var.canary_weight
      }
      target_group {
        arn    = aws_lb_target_group.api["canary"].arn
        weight = var.canary_weight
      }
    }
  }
}

resource "aws_ecs_service" "svc" {
  for_each        = local.services
  name            = each.key
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.svc[each.key].arn
  desired_count   = each.key == "worker" ? var.worker_min : 1
  launch_type     = "FARGATE"
  network_configuration {
    subnets         = var.private_subnet_ids
    security_groups = [var.app_sg_id]
  }
  dynamic "load_balancer" {
    for_each = each.key == "api" ? [1] : []
    content {
      target_group_arn = aws_lb_target_group.api["stable"].arn
      container_name   = "api"
      container_port   = 8000
    }
  }
}

# Workers autoscale on queue depth (backlog), not CPU — an LLM worker mostly waits on the network.
resource "aws_appautoscaling_target" "worker" {
  service_namespace  = "ecs"
  resource_id        = "service/${aws_ecs_cluster.this.name}/${aws_ecs_service.svc["worker"].name}"
  scalable_dimension = "ecs:service:DesiredCount"
  min_capacity       = var.worker_min
  max_capacity       = var.worker_max
}

resource "aws_appautoscaling_policy" "worker_backlog" {
  name               = "atlas-${var.env}-worker-backlog"
  service_namespace  = "ecs"
  resource_id        = aws_appautoscaling_target.worker.resource_id
  scalable_dimension = aws_appautoscaling_target.worker.scalable_dimension
  policy_type        = "TargetTrackingScaling"
  target_tracking_scaling_policy_configuration {
    target_value = 20
    customized_metric_specification {
      metric_name = "ApproximateNumberOfMessagesVisible"
      namespace   = "AWS/SQS"
      statistic   = "Average"
      dimensions {
        name  = "QueueName"
        value = var.queue_name
      }
    }
  }
}

resource "aws_cloudwatch_metric_alarm" "dlq_not_empty" {
  alarm_name          = "atlas-${var.env}-queue-depth-high"
  alarm_description   = "Runbook RB-03: queue depth spike (tenant bulk?)"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  dimensions          = { QueueName = var.queue_name }
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 2
  threshold           = 500
  comparison_operator = "GreaterThanThreshold"
}

output "api_url" { value = "http://${aws_lb.api.dns_name}" }

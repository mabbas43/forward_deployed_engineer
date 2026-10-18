variable "env" { type = string }
variable "vpc_id" { type = string }
variable "private_subnet_ids" { type = list(string) }
variable "app_sg_id" { type = string }

# --- SQS FIFO + DLQ: MessageGroupId = tenant (fairness), dedup ids (idempotency) ---------------------
resource "aws_sqs_queue" "dlq" {
  name       = "atlas-${var.env}-tickets-dlq.fifo"
  fifo_queue = true
}

resource "aws_sqs_queue" "tickets" {
  name                       = "atlas-${var.env}-tickets.fifo"
  fifo_queue                 = true
  deduplication_scope        = "messageGroup"
  fifo_throughput_limit      = "perMessageGroupId"
  visibility_timeout_seconds = 360 # MUST exceed the graph deadline (300 s) — see ARCHITECTURE.md
  redrive_policy             = jsonencode({ deadLetterTargetArn = aws_sqs_queue.dlq.arn, maxReceiveCount = 3 })
}

# --- Aurora Serverless v2 Postgres (pgvector): checkpoints, store, audit (INSERT-only role), metrics ---
resource "aws_db_subnet_group" "this" {
  name       = "atlas-${var.env}"
  subnet_ids = var.private_subnet_ids
}

resource "aws_rds_cluster" "pg" {
  cluster_identifier          = "atlas-${var.env}"
  engine                      = "aurora-postgresql"
  engine_mode                 = "provisioned"
  engine_version              = "16.6"
  database_name               = "atlas"
  master_username             = "atlas_admin"
  manage_master_user_password = true
  db_subnet_group_name        = aws_db_subnet_group.this.name
  vpc_security_group_ids      = [var.app_sg_id]
  storage_encrypted           = true
  backup_retention_period     = 7
  skip_final_snapshot         = var.env != "prod"
  serverlessv2_scaling_configuration {
    min_capacity = 0.5
    max_capacity = 8
  }
}

resource "aws_rds_cluster_instance" "pg" {
  count              = 2 # multi-AZ: failover is a row in the failure-modes table
  cluster_identifier = aws_rds_cluster.pg.id
  instance_class     = "db.serverless"
  engine             = aws_rds_cluster.pg.engine
  engine_version     = aws_rds_cluster.pg.engine_version
}

# --- ElastiCache Redis: exact/semantic cache, token buckets, dedupe, event streams ---------------------
resource "aws_elasticache_subnet_group" "this" {
  name       = "atlas-${var.env}"
  subnet_ids = var.private_subnet_ids
}

resource "aws_elasticache_replication_group" "redis" {
  replication_group_id       = "atlas-${var.env}"
  description                = "atlas cache/buckets/streams"
  engine                     = "redis"
  node_type                  = "cache.t4g.small"
  num_cache_clusters         = 2
  automatic_failover_enabled = true
  transit_encryption_enabled = true
  at_rest_encryption_enabled = true
  subnet_group_name          = aws_elasticache_subnet_group.this.name
  security_group_ids         = [var.app_sg_id]
}

output "queue_url" { value = aws_sqs_queue.tickets.url }
output "queue_arn" { value = aws_sqs_queue.tickets.arn }
output "queue_name" { value = aws_sqs_queue.tickets.name }
output "db_secret_arn" { value = aws_rds_cluster.pg.master_user_secret[0].secret_arn }
output "redis_endpoint" { value = aws_elasticache_replication_group.redis.primary_endpoint_address }

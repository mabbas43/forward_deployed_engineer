# ATLAS on AWS (eu-central-1): VPC → Aurora Serverless v2 (checkpoints/store/audit/metrics, pgvector)
# + ElastiCache Redis (cache, buckets, streams) + SQS FIFO with DLQ (tickets) → ECS Fargate services.
module "network" {
  source = "./modules/network"
  env    = var.env
}

module "data" {
  source             = "./modules/data"
  env                = var.env
  vpc_id             = module.network.vpc_id
  private_subnet_ids = module.network.private_subnet_ids
  app_sg_id          = module.network.app_sg_id
}

module "compute" {
  source             = "./modules/compute"
  env                = var.env
  region             = var.region
  image              = var.image
  vpc_id             = module.network.vpc_id
  public_subnet_ids  = module.network.public_subnet_ids
  private_subnet_ids = module.network.private_subnet_ids
  app_sg_id          = module.network.app_sg_id
  queue_url          = module.data.queue_url
  queue_arn          = module.data.queue_arn
  queue_name         = module.data.queue_name
  db_secret_arn      = module.data.db_secret_arn
  redis_endpoint     = module.data.redis_endpoint
  worker_min         = var.worker_min
  worker_max         = var.worker_max
  canary_weight      = var.canary_weight
}

resource "aws_secretsmanager_secret" "app" {
  name = "atlas/${var.env}/app" # OPENAI/ANTHROPIC keys, JWT secret, LangSmith key — set out of band
}

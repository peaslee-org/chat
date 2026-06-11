terraform {
  backend "s3" {
    bucket         = "chat-api-tfstate"
    key            = "chat-api/staging/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "terraform-state-lock"
    encrypt        = true
  }
}

module "networking" {
  source = "../../modules/networking"
  environment = "staging"
}

module "ecs" {
  source      = "../../modules/ecs"
  environment = "staging"
  vpc_id      = module.networking.vpc_id
  subnet_ids  = module.networking.private_subnet_ids
}

module "rds" {
  source      = "../../modules/rds"
  environment = "staging"
  vpc_id      = module.networking.vpc_id
  subnet_ids  = module.networking.private_subnet_ids
}

module "monitoring" {
  source      = "../../modules/monitoring"
  environment = "staging"
}

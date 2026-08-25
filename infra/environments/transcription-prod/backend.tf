terraform {
  required_version = ">= 1.10.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }

  backend "s3" {
    # bucket is supplied at init time: terraform init -backend-config=backend.hcl
    key          = "transcription-worker/prod/v2/terraform.tfstate"
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true
  }
}

provider "aws" {
  region = var.aws_region

  # Cost-allocation / console-applied tags are not this code's business.
  ignore_tags {
    key_prefixes = ["user:"]
  }
}

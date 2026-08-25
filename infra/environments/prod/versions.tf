provider "aws" {
  region = var.aws_region

  # Cost-allocation / console-applied tags are not this code's business.
  ignore_tags {
    key_prefixes = ["user:"]
  }
}

terraform {
  required_version = ">= 1.10.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.0"
    }
  }
}

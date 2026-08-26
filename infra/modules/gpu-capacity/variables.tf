variable "environment" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "subnet_ids" {
  type = list(string)
}

variable "cluster_name" {
  type        = string
  description = "ECS cluster the capacity provider attaches to (string, not a module output — avoids an ecs↔gpu cycle)."
}

variable "ami_id" {
  type        = string
  description = "Pre-baked ECS GPU AMI (scripts/deploy/build-gpu-ami.sh). Pinned on purpose."
}

variable "instance_type" {
  type    = string
  default = "g4dn.xlarge"
}

variable "max_size" {
  type        = number
  default     = 2
  description = "Hard ceiling. Nothing in the app can raise it."
}

variable "root_volume_gb" {
  type    = number
  default = 80
}

variable "cost_tag_key" {
  type    = string
  default = "CostCenter"
}

variable "cost_tag_value" {
  type    = string
  default = "gpu"
}

variable "alert_email" {
  type        = string
  default     = ""
  description = "Empty disables the SNS topic, the 4-hour alarm and the Budget notifications."
}

variable "budget_actual_usd" {
  type    = number
  default = 40
}

variable "budget_forecast_usd" {
  type    = number
  default = 60
}

variable "budget_start" {
  type    = string
  default = "2026-08-01_00:00"
}

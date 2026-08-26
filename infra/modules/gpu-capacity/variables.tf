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

variable "instance_types" {
  description = "GPU instance types the pool may launch (mixed-instances overrides). Wider = more spot pools. All must run the tenants' CUDA images."
  type        = list(string)
  default     = ["g4dn.xlarge", "g4dn.2xlarge", "g5.xlarge", "g6.xlarge"]
}

variable "spot_allocation_strategy" {
  description = "lowest-price (default; the only strategy an existing ASG accepts in place — see main.tf) with spot_instance_pools pools, or capacity-optimized on a fresh ASG."
  type        = string
  default     = "lowest-price"
}

variable "spot_instance_pools" {
  description = "Pools for lowest-price: with 4 instance types x 5 AZs, 20 means every combination is tried."
  type        = number
  default     = 20
}

variable "on_demand_percentage" {
  description = "Percent of capacity above base launched on-demand. 0 = all spot; 100 = all on-demand (reliable, ~3x the price; the hour caps still bound it)."
  type        = number
  default     = 0
}

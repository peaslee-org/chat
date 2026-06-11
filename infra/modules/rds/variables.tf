variable "environment" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "vpc_cidr" {
  type = string
}

variable "subnet_ids" {
  type = list(string)
}

variable "db_name" {
  type    = string
  default = "chatapi"
}

variable "db_username" {
  type    = string
  default = "chatapi"
}

variable "db_password" {
  type      = string
  sensitive = true
}

variable "instance_class" {
  type    = string
  default = "db.t3.micro"
}

variable "allocated_storage" {
  type    = number
  default = 20
}

variable "subnet_group_name" {
  type        = string
  default     = null
  description = "Override the DB subnet group name. Defaults to chat-api-<environment>."
}

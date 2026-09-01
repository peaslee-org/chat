variable "domain_name" {
  type = string
}

variable "subject_alternative_names" {
  type        = list(string)
  description = "Additional domain names on the certificate (e.g. the aitools alias). Changing this replaces the certificate."
  default     = []
}

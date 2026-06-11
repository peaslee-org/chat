output "certificate_arn" {
  value = aws_acm_certificate.this.arn
}

output "validation_records" {
  description = "Add these CNAME records to your DNS provider, then wait for the certificate status to become 'Issued' in AWS Console → Certificate Manager before running the full terraform apply."
  value = {
    for dvo in aws_acm_certificate.this.domain_validation_options : dvo.domain_name => {
      name  = dvo.resource_record_name
      type  = dvo.resource_record_type
      value = dvo.resource_record_value
    }
  }
}

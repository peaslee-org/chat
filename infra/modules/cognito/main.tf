resource "aws_cognito_user_pool" "this" {
  name = "chat-api-${var.environment}"

  password_policy {
    minimum_length    = 8
    require_uppercase = true
    require_lowercase = true
    require_numbers   = true
    require_symbols   = false
  }

  auto_verified_attributes = ["email"]

  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }

  tags = {
    Environment = var.environment
  }
}

resource "aws_cognito_user_pool_client" "this" {
  name         = "chat-api-${var.environment}"
  user_pool_id = aws_cognito_user_pool.this.id

  explicit_auth_flows = [
    "ALLOW_USER_PASSWORD_AUTH",
    "ALLOW_REFRESH_TOKEN_AUTH",
  ]

  token_validity_units {
    access_token  = "hours"
    refresh_token = "days"
  }

  access_token_validity  = 1
  refresh_token_validity = 30

  prevent_user_existence_errors = "ENABLED"
}

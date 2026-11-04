variable "aws_region" {
  type    = string
  default = "us-east-1"
}
variable "project_name" {
  type    = string
  default = "cloudops-arena"
}
variable "lambda_package_path" {
  type        = string
  description = "Path to the ZIP produced by scripts/build-api-lambda.sh"
  default     = "../../build/api-lambda.zip"
}
variable "jwt_secret" {
  type      = string
  sensitive = true
}
variable "admin_username" {
  type    = string
  default = "arena-admin"
}
variable "admin_password" {
  type      = string
  sensitive = true
}
variable "github_webhook_secret" {
  type      = string
  sensitive = true
  default   = ""
}
variable "cors_origins" {
  type    = list(string)
  default = ["http://localhost:5173"]
}

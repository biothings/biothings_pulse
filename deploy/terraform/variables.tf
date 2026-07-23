variable "aws_region" {
  type        = string
  default     = "us-west-2"
  description = "AWS region to deploy into."
}

variable "project_name" {
  type        = string
  default     = "biothings-pulse"
  description = "Name prefix for all created resources."
}

variable "container_image" {
  type        = string
  description = "Full image URI (e.g. <acct>.dkr.ecr.<region>.amazonaws.com/biothings-pulse:latest). Defaults to the ECR repo created here at :latest."
  default     = ""
}

variable "container_port" {
  type    = number
  default = 8080
}

variable "cpu" {
  type        = number
  default     = 512
  description = "Fargate task CPU units (512 = 0.5 vCPU)."
}

variable "memory" {
  type        = number
  default     = 1024
  description = "Fargate task memory (MiB)."
}

variable "desired_count" {
  type        = number
  default     = 1
  description = "Number of tasks. Keep at 1 while using the in-app scheduler."
}

variable "scheduler_enabled" {
  type        = bool
  default     = true
  description = "Run the in-app refresh scheduler. Set false and use EventBridge for >1 task."
}

variable "scheduler_interval" {
  type    = number
  default = 86400
}

variable "vpc_id" {
  type        = string
  default     = ""
  description = "VPC to use. Empty = default VPC."
}

variable "subnet_ids" {
  type        = list(string)
  default     = []
  description = "Subnets for the ALB + tasks. Empty = default VPC subnets."
}

variable "extra_environment" {
  type        = map(string)
  default     = {}
  description = "Additional PULSE_* environment variables for the container."
}

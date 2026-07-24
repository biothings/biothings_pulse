output "ecr_repository_url" {
  value       = aws_ecr_repository.this.repository_url
  description = "Push the built image here, then apply again (or set container_image)."
}

output "alb_dns_name" {
  value       = aws_lb.this.dns_name
  description = "Public URL: http://<this>/ (dashboard), /api/health, /api/docs, /api/sources ..."
}

output "dynamodb_table" {
  value = aws_dynamodb_table.state.name
}

output "ecs_cluster" {
  value = aws_ecs_cluster.this.name
}

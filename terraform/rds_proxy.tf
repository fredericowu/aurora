# RDS Proxy for improved connection management
# Reduces connection overhead and improves Lambda cold start performance

# Secret Manager for RDS credentials
resource "aws_secretsmanager_secret" "rds_credentials" {
  name                    = "aurora-rds-credentials-v2"
  description             = "RDS database credentials for Aurora Search API"
  recovery_window_in_days = 0

  tags = {
    Name = "aurora-rds-credentials"
  }
}

resource "aws_secretsmanager_secret_version" "rds_credentials" {
  secret_id = aws_secretsmanager_secret.rds_credentials.id
  secret_string = jsonencode({
    username = var.db_username
    password = var.db_password
  })
}

# IAM Role for RDS Proxy
resource "aws_iam_role" "rds_proxy" {
  name = "aurora-rds-proxy-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "rds.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    Name = "aurora-rds-proxy-role"
  }
}

# IAM Policy for RDS Proxy to access Secrets Manager
resource "aws_iam_role_policy" "rds_proxy_secrets" {
  name = "aurora-rds-proxy-secrets-policy"
  role = aws_iam_role.rds_proxy.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue"
        ]
        Resource = aws_secretsmanager_secret.rds_credentials.arn
      }
    ]
  })
}

# RDS Proxy
resource "aws_db_proxy" "main" {
  name                   = "aurora-search-proxy"
  engine_family          = "POSTGRESQL"
  auth {
    auth_scheme = "SECRETS"
    iam_auth    = "DISABLED"
    secret_arn  = aws_secretsmanager_secret.rds_credentials.arn
  }

  role_arn               = aws_iam_role.rds_proxy.arn
  vpc_subnet_ids         = aws_subnet.private[*].id
  vpc_security_group_ids = [aws_security_group.rds_proxy.id]
  require_tls            = false

  tags = {
    Name = "aurora-search-proxy"
  }

  depends_on = [
    aws_secretsmanager_secret_version.rds_credentials
  ]
}

# RDS Proxy Default Target Group
resource "aws_db_proxy_default_target_group" "main" {
  db_proxy_name = aws_db_proxy.main.name

  connection_pool_config {
    connection_borrow_timeout    = 120
    max_connections_percent      = 100
    max_idle_connections_percent = 50
  }
}

# RDS Proxy Target
resource "aws_db_proxy_target" "main" {
  db_instance_identifier = aws_db_instance.main.identifier
  db_proxy_name          = aws_db_proxy.main.name
  target_group_name      = aws_db_proxy_default_target_group.main.name
}

# Security Group for RDS Proxy
resource "aws_security_group" "rds_proxy" {
  name        = "aurora-rds-proxy-sg"
  description = "Security group for RDS Proxy"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "PostgreSQL from Lambda"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.lambda.id]
  }

  egress {
    description = "PostgreSQL to RDS"
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    security_groups = [aws_security_group.rds.id]
  }

  tags = {
    Name = "aurora-rds-proxy-sg"
  }
}

# Update RDS security group to allow RDS Proxy
resource "aws_security_group_rule" "rds_from_proxy" {
  type                     = "ingress"
  from_port                = 5432
  to_port                  = 5432
  protocol                 = "tcp"
  security_group_id        = aws_security_group.rds.id
  source_security_group_id = aws_security_group.rds_proxy.id
  description              = "PostgreSQL from RDS Proxy"
}

# Attach security group to RDS Proxy
resource "aws_db_proxy_endpoint" "read_write" {
  db_proxy_name          = aws_db_proxy.main.name
  db_proxy_endpoint_name = "aurora-proxy-rw-endpoint"
  vpc_subnet_ids         = aws_subnet.private[*].id
  vpc_security_group_ids = [aws_security_group.rds_proxy.id]
  target_role            = "READ_WRITE"

  tags = {
    Name = "aurora-proxy-rw-endpoint"
  }
}


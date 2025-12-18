# DB Subnet Group - using Lambda VPC's private subnets
# Using a new name to avoid conflict with existing subnet group in different VPC
resource "aws_db_subnet_group" "main" {
  name       = "aurora-db-subnet-group-v2"
  subnet_ids = aws_subnet.private[*].id

  tags = {
    Name = "aurora-db-subnet-group"
  }

  lifecycle {
    create_before_destroy = true
  }
}

# RDS PostgreSQL Instance
resource "aws_db_instance" "main" {
  identifier             = "aurora-postgres"
  engine                 = "postgres"
  # engine_version will use default (latest stable)
  instance_class         = var.db_instance_class
  allocated_storage     = 20
  storage_type           = "gp3"
  storage_encrypted      = true
  db_name                = var.db_name
  username               = var.db_username
  password               = var.db_password
  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.rds.id]
  publicly_accessible    = false
  skip_final_snapshot    = true
  backup_retention_period = 7
  backup_window          = "03:00-04:00"
  maintenance_window     = "mon:04:00-mon:05:00"

  tags = {
    Name = "aurora-postgres-db"
  }
}

# Database initialization script (stored as local file, executed via ingestion script)
# The schema will be created by the ingestion script on first run

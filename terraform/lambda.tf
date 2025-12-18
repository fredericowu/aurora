# IAM Role for Lambda
resource "aws_iam_role" "lambda" {
  name = "aurora-lambda-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    Name = "aurora-lambda-role"
  }

  lifecycle {
    create_before_destroy = true
  }
}

# IAM Policy for Lambda VPC access
resource "aws_iam_role_policy_attachment" "lambda_vpc" {
  role       = aws_iam_role.lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

# Lambda Function
resource "aws_lambda_function" "search_api" {
  filename         = "${path.module}/lambda_function.zip"
  function_name    = "aurora-search-api"
  role            = aws_iam_role.lambda.arn
  handler         = "handler.handler"
  runtime         = "python3.13"
  timeout         = 30
  memory_size     = 1024
  architectures    = ["x86_64"]

  vpc_config {
    subnet_ids         = aws_subnet.private[*].id
    security_group_ids = [aws_security_group.lambda.id]
  }

  environment {
    variables = {
      DB_HOST     = aws_db_instance.main.address
      DB_PORT     = tostring(aws_db_instance.main.port)
      DB_NAME     = aws_db_instance.main.db_name
      DB_USER     = aws_db_instance.main.username
      DB_PASSWORD = var.db_password
    }
  }

  source_code_hash = filebase64sha256("${path.module}/lambda_function.zip")

  tags = {
    Name = "aurora-search-api"
  }
}

# CloudWatch Log Group for Lambda
resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${aws_lambda_function.search_api.function_name}"
  retention_in_days = 14

  tags = {
    Name = "aurora-lambda-logs"
  }
}


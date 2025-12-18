.PHONY: help deploy destroy plan init-terraform setup-env ingest performance-test test-lambda clean clean-venv venv setup-python build-lambda check-env create-terraform-backend import-existing

# Default target
help:
	@echo "Aurora Search Engine - Makefile"
	@echo ""
	@echo "Available targets:"
	@echo "  make venv              - Create Python virtual environment"
	@echo "  make setup-python      - Install Python dependencies"
	@echo "  make build-lambda      - Build Lambda deployment package (x86_64)"
	@echo "  make init-terraform    - Initialize Terraform"
	@echo "  make plan              - Plan Terraform changes"
	@echo "  make deploy            - Build Lambda and deploy infrastructure"
	@echo "  make destroy           - Destroy infrastructure (with confirmation)"
	@echo "  make setup-env         - Setup environment (works in local & CI)"
	@echo "  make ingest            - Run message ingestion"
	@echo "  make performance-test  - Run performance tests"
	@echo "  make test-lambda       - Test Lambda function via API Gateway"
	@echo "  make clean             - Clean temporary files"
	@echo "  make clean-venv        - Remove Python virtual environment"
	@echo ""

# Python virtual environment
VENV := .venv
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip

# Create virtual environment
venv:
	@if [ ! -d "$(VENV)" ]; then \
		echo "Creating Python virtual environment..."; \
		python3 -m venv $(VENV); \
		echo "✓ Virtual environment created"; \
	else \
		echo "✓ Virtual environment already exists"; \
	fi

# Setup Python dependencies
setup-python: venv
	@echo "Installing Python dependencies..."
	@$(PIP) install --upgrade pip
	@$(PIP) install -r scripts/requirements.txt
	@echo "✓ Python dependencies installed"

# Load environment variables from .env file (if it exists)
-include .env
export

# Terraform directory
TF_DIR := terraform
TF_VAR_db_password ?= $(DB_PASSWORD)

# Check if required variables are set
check-env:
	@if [ -z "$$AWS_ACCESS_KEY_ID" ]; then \
		echo "Error: AWS_ACCESS_KEY_ID not set in .env or environment"; \
		exit 1; \
	fi
	@if [ -z "$$AWS_SECRET_ACCESS_KEY" ]; then \
		echo "Error: AWS_SECRET_ACCESS_KEY not set in .env or environment"; \
		exit 1; \
	fi
	@if [ -z "$$DB_PASSWORD" ]; then \
		echo "Error: DB_PASSWORD not set in .env or environment"; \
		exit 1; \
	fi
	@echo "✓ Environment variables validated"

# Create S3 bucket for Terraform state (if it doesn't exist)
create-terraform-backend: check-env
	@echo "Creating Terraform backend resources..."
	@AWS_REGION=$${AWS_REGION:-us-east-1}; \
	BUCKET_NAME="aurora-terraform-state-$${AWS_REGION}"; \
	TABLE_NAME="aurora-terraform-locks"; \
	echo "Checking S3 bucket: $$BUCKET_NAME"; \
	if ! aws s3 ls "s3://$$BUCKET_NAME" 2>/dev/null >/dev/null 2>&1; then \
		echo "Creating S3 bucket: $$BUCKET_NAME"; \
		aws s3 mb "s3://$$BUCKET_NAME" --region $$AWS_REGION || true; \
		aws s3api put-bucket-versioning \
			--bucket $$BUCKET_NAME \
			--versioning-configuration Status=Enabled 2>/dev/null || true; \
		aws s3api put-bucket-encryption \
			--bucket $$BUCKET_NAME \
			--server-side-encryption-configuration '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}' 2>/dev/null || true; \
		echo "✓ S3 bucket created"; \
	else \
		echo "✓ S3 bucket already exists"; \
	fi; \
	echo "Checking DynamoDB table: $$TABLE_NAME"; \
	if ! aws dynamodb describe-table --table-name $$TABLE_NAME --region $$AWS_REGION 2>/dev/null >/dev/null 2>&1; then \
		echo "Creating DynamoDB table: $$TABLE_NAME"; \
		aws dynamodb create-table \
			--table-name $$TABLE_NAME \
			--attribute-definitions AttributeName=LockID,AttributeType=S \
			--key-schema AttributeName=LockID,KeyType=HASH \
			--billing-mode PAY_PER_REQUEST \
			--region $$AWS_REGION 2>/dev/null || true; \
		echo "Waiting for table to be active..."; \
		aws dynamodb wait table-exists --table-name $$TABLE_NAME --region $$AWS_REGION 2>/dev/null || sleep 5; \
		echo "✓ DynamoDB table created"; \
	else \
		echo "✓ DynamoDB table already exists"; \
	fi

# Import existing resources
import-existing: check-env
	@echo "Importing existing resources..."
	@cd $(TF_DIR) && \
	terraform import -var="db_password=$(TF_VAR_db_password)" aws_cloudwatch_log_group.api_gateway /aws/apigateway/aurora-search-api 2>/dev/null || echo "Log group may already be in state"; \
	terraform import -var="db_password=$(TF_VAR_db_password)" aws_db_subnet_group.main aurora-db-subnet-group 2>/dev/null || echo "DB subnet group may already be in state"; \
	terraform import -var="db_password=$(TF_VAR_db_password)" aws_iam_role.lambda aurora-lambda-role 2>/dev/null || echo "IAM role may already be in state"

# Initialize Terraform
init-terraform: check-env create-terraform-backend
	@echo "Initializing Terraform..."
	cd $(TF_DIR) && terraform init

# Plan Terraform changes
plan: init-terraform
	@echo "Planning Terraform changes..."
	cd $(TF_DIR) && terraform plan -var="db_password=$(TF_VAR_db_password)"

# Build Lambda deployment package
build-lambda:
	@echo "Building Lambda deployment package for x86_64..."
	# @sudo rm -rf $(TF_DIR)/lambda_package || rm -rf $(TF_DIR)/lambda_package || true
	# @rm -f $(TF_DIR)/lambda_function.zip
	@mkdir -p $(TF_DIR)/lambda_package
	@echo "Installing dependencies for Linux x86_64..."
	@docker run --rm --platform linux/amd64 \
		--entrypoint /bin/bash \
		--user $(shell id -u):$(shell id -g) \
		-v $(shell pwd)/lambda:/lambda:ro \
		-v $(shell pwd)/$(TF_DIR)/lambda_package:/package \
		public.ecr.aws/lambda/python:3.13 \
		-c "pip install -r /lambda/requirements.txt -t /package --no-cache-dir && chmod -R 755 /package"
	@echo "Copying Lambda code..."
	@cp lambda/*.py $(TF_DIR)/lambda_package/
	@echo "Creating deployment package..."
	@cd $(TF_DIR)/lambda_package && zip -r ../lambda_function.zip . -q
	@rm -rf $(TF_DIR)/lambda_package
	@echo "✓ Lambda deployment package created: $(TF_DIR)/lambda_function.zip"
	@ls -lh $(TF_DIR)/lambda_function.zip

# Deploy infrastructure
deploy: check-env build-lambda init-terraform
	@echo "Deploying infrastructure..."
	@echo "This may take 10-15 minutes..."
	cd $(TF_DIR) && terraform apply -auto-approve -var="db_password=$(TF_VAR_db_password)" || (echo "Deployment failed. Check errors above." && exit 1)
	@echo ""
	@echo "✓ Infrastructure deployed successfully!"
	@echo "Run 'make setup-env' to populate .env with output values"

# Destroy infrastructure
destroy: check-env
	@echo "⚠️  WARNING: This will destroy all infrastructure!"
	@read -p "Are you sure? [y/N] " -n 1 -r; \
	echo; \
	if [[ $$REPLY =~ ^[Yy]$$ ]]; then \
		cd $(TF_DIR) && terraform destroy -auto-approve -var="db_password=$(TF_VAR_db_password)"; \
	fi

# Setup environment variables from Terraform outputs
# Works in both local and CI environments
setup-env: check-env
	@echo "Retrieving values from Terraform outputs..."
	@cd $(TF_DIR) && terraform output -json > /tmp/terraform_outputs.json 2>/dev/null || (echo "Error: Terraform outputs not available. Run 'make deploy' first." && exit 1)
	@echo ""
	@DB_HOST=$$(cd $(TF_DIR) && terraform output -raw rds_endpoint 2>/dev/null); \
	DB_PORT=$$(cd $(TF_DIR) && terraform output -raw rds_port 2>/dev/null); \
	DB_NAME=$$(cd $(TF_DIR) && terraform output -raw rds_database_name 2>/dev/null); \
	API_URL=$$(cd $(TF_DIR) && terraform output -raw api_gateway_url 2>/dev/null); \
	if [ -n "$$GITHUB_ENV" ]; then \
		echo "Setting up environment for GitHub Actions..."; \
		echo "DB_HOST=$$DB_HOST" >> $$GITHUB_ENV; \
		echo "DB_PORT=$$DB_PORT" >> $$GITHUB_ENV; \
		echo "DB_NAME=$$DB_NAME" >> $$GITHUB_ENV; \
		echo "API_BASE_URL=$$API_URL" >> $$GITHUB_ENV; \
		echo "✓ Environment variables exported to GitHub Actions"; \
	else \
		echo "Updating .env file..."; \
		if [ -n "$$DB_HOST" ]; then \
			if grep -q "^DB_HOST=" .env 2>/dev/null; then \
				sed -i.bak "s|^DB_HOST=.*|DB_HOST=$$DB_HOST|" .env; \
			else \
				echo "DB_HOST=$$DB_HOST" >> .env; \
			fi; \
			echo "  ✓ DB_HOST=$$DB_HOST"; \
		fi; \
		if [ -n "$$DB_PORT" ]; then \
			if grep -q "^DB_PORT=" .env 2>/dev/null; then \
				sed -i.bak "s|^DB_PORT=.*|DB_PORT=$$DB_PORT|" .env; \
			else \
				echo "DB_PORT=$$DB_PORT" >> .env; \
			fi; \
			echo "  ✓ DB_PORT=$$DB_PORT"; \
		fi; \
		if [ -n "$$DB_NAME" ]; then \
			if grep -q "^DB_NAME=" .env 2>/dev/null; then \
				sed -i.bak "s|^DB_NAME=.*|DB_NAME=$$DB_NAME|" .env; \
			else \
				echo "DB_NAME=$$DB_NAME" >> .env; \
			fi; \
			echo "  ✓ DB_NAME=$$DB_NAME"; \
		fi; \
		if [ -n "$$API_URL" ]; then \
			if grep -q "^API_BASE_URL=" .env 2>/dev/null; then \
				sed -i.bak "s|^API_BASE_URL=.*|API_BASE_URL=$$API_URL|" .env; \
			else \
				echo "API_BASE_URL=$$API_URL" >> .env; \
			fi; \
			echo "  ✓ API_BASE_URL=$$API_URL"; \
		fi; \
		rm -f .env.bak 2>/dev/null || true; \
		echo ""; \
		echo "✓ .env file updated with Terraform outputs"; \
	fi

# Run message ingestion via Lambda
ingest:
	@echo "Running message ingestion via Lambda..."
	@if [ -z "$(API_BASE_URL)" ]; then \
		echo "Error: API_BASE_URL not set. Run 'make setup-env' first."; \
		exit 1; \
	fi
	@echo "This may take several minutes depending on the number of messages..."
	@curl -X POST "$(API_BASE_URL)/ingest" -H "Content-Type: application/json" | python3 -m json.tool
	@echo ""
	@echo "✓ Ingestion complete"

# Run performance tests
performance-test: setup-python
	@echo "Running performance tests..."
	@if [ -z "$(API_BASE_URL)" ]; then \
		echo "Error: API_BASE_URL not set. Run 'make setup-env' first."; \
		exit 1; \
	fi
	@$(PIP) install -q requests
	@cd scripts && ../$(PYTHON) performance_test.py

# Test Lambda function directly
test-lambda:
	@echo "Testing Lambda function via API Gateway..."
	@if [ -z "$(API_BASE_URL)" ]; then \
		echo "Error: API_BASE_URL not set. Run 'make setup-env' first."; \
		exit 1; \
	fi
	@echo ""
	@echo "1. Testing health endpoint..."
	@curl -s "$(API_BASE_URL)/health" | python3 -m json.tool || echo "Health check failed"
	@echo ""
	@echo "2. Testing root endpoint..."
	@curl -s "$(API_BASE_URL)/" | python3 -m json.tool || echo "Root endpoint failed"
	@echo ""
	@echo "3. Testing search endpoint (query: 'test')..."
	@curl -s "$(API_BASE_URL)/search?q=test&limit=5" | python3 -m json.tool || echo "Search failed"
	@echo ""
	@echo "✓ Lambda tests complete"

# Clean temporary files
clean:
	@echo "Cleaning temporary files..."
	rm -f /tmp/terraform_outputs.json
	rm -f .env.bak
	cd $(TF_DIR) && rm -f terraform.tfplan
	rm -rf $(TF_DIR)/lambda_package
	@echo "✓ Cleaned"

# Clean virtual environment (optional)
clean-venv:
	@echo "Removing virtual environment..."
	rm -rf $(VENV)
	@echo "✓ Virtual environment removed"


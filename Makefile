.PHONY: help deploy destroy plan init-terraform setup-env ingest test clean

# Default target
help:
	@echo "Aurora Search Engine - Makefile"
	@echo ""
	@echo "Available targets:"
	@echo "  make init-terraform  - Initialize Terraform"
	@echo "  make plan           - Plan Terraform changes"
	@echo "  make deploy         - Deploy infrastructure"
	@echo "  make destroy        - Destroy infrastructure"
	@echo "  make setup-env      - Populate .env from Terraform outputs"
	@echo "  make ingest         - Run message ingestion"
	@echo "  make test           - Run performance tests"
	@echo "  make clean          - Clean temporary files"
	@echo ""

# Load environment variables from .env file (if it exists)
-include .env
export

# Terraform directory
TF_DIR := terraform
TF_VAR_db_password ?= $(DB_PASSWORD)

# Check if required variables are set
check-env:
	@if [ -z "$(AWS_ACCESS_KEY_ID)" ]; then \
		echo "Error: AWS_ACCESS_KEY_ID not set in .env or environment"; \
		exit 1; \
	fi
	@if [ -z "$(AWS_SECRET_ACCESS_KEY)" ]; then \
		echo "Error: AWS_SECRET_ACCESS_KEY not set in .env or environment"; \
		exit 1; \
	fi
	@if [ -z "$(DB_PASSWORD)" ]; then \
		echo "Error: DB_PASSWORD not set in .env or environment"; \
		exit 1; \
	fi
	@echo "✓ Environment variables validated"

# Initialize Terraform
init-terraform: check-env
	@echo "Initializing Terraform..."
	cd $(TF_DIR) && terraform init

# Plan Terraform changes
plan: init-terraform
	@echo "Planning Terraform changes..."
	cd $(TF_DIR) && terraform plan -var="db_password=$(TF_VAR_db_password)"

# Deploy infrastructure
deploy: check-env init-terraform
	@echo "Deploying infrastructure..."
	cd $(TF_DIR) && terraform apply -auto-approve -var="db_password=$(TF_VAR_db_password)"
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
setup-env: check-env
	@echo "Retrieving values from Terraform outputs..."
	@cd $(TF_DIR) && terraform output -json > /tmp/terraform_outputs.json 2>/dev/null || (echo "Error: Terraform outputs not available. Run 'make deploy' first." && exit 1)
	@echo ""
	@echo "Updating .env file with Terraform outputs..."
	@DB_HOST=$$(cd $(TF_DIR) && terraform output -raw rds_endpoint 2>/dev/null); \
	DB_PORT=$$(cd $(TF_DIR) && terraform output -raw rds_port 2>/dev/null); \
	DB_NAME=$$(cd $(TF_DIR) && terraform output -raw rds_database_name 2>/dev/null); \
	API_URL=$$(cd $(TF_DIR) && terraform output -raw api_gateway_url 2>/dev/null); \
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
	echo "✓ .env file updated with Terraform outputs"

# Run message ingestion
ingest: setup-env
	@echo "Running message ingestion..."
	@if [ -z "$(DB_HOST)" ]; then \
		echo "Error: DB_HOST not set. Run 'make setup-env' first."; \
		exit 1; \
	fi
	cd scripts && \
	pip install -q -r requirements.txt && \
	python ingest.py

# Run performance tests
test: setup-env
	@echo "Running performance tests..."
	@if [ -z "$(API_BASE_URL)" ]; then \
		echo "Error: API_BASE_URL not set. Run 'make setup-env' first."; \
		exit 1; \
	fi
	cd scripts && \
	pip install -q requests && \
	python performance_test.py

# Clean temporary files
clean:
	@echo "Cleaning temporary files..."
	rm -f /tmp/terraform_outputs.json
	rm -f .env.bak
	cd $(TF_DIR) && rm -f terraform.tfplan
	@echo "✓ Cleaned"

# GitHub Actions compatible targets (no interactive prompts)
deploy-ci: check-env init-terraform
	@echo "Deploying infrastructure (CI mode)..."
	cd $(TF_DIR) && terraform apply -auto-approve -var="db_password=$(TF_VAR_db_password)"

setup-env-ci: check-env
	@echo "Setting up environment (CI mode)..."
	@DB_HOST=$$(cd $(TF_DIR) && terraform output -raw rds_endpoint 2>/dev/null); \
	DB_PORT=$$(cd $(TF_DIR) && terraform output -raw rds_port 2>/dev/null); \
	DB_NAME=$$(cd $(TF_DIR) && terraform output -raw rds_database_name 2>/dev/null); \
	API_URL=$$(cd $(TF_DIR) && terraform output -raw api_gateway_url 2>/dev/null); \
	echo "DB_HOST=$$DB_HOST" >> $$GITHUB_ENV; \
	echo "DB_PORT=$$DB_PORT" >> $$GITHUB_ENV; \
	echo "DB_NAME=$$DB_NAME" >> $$GITHUB_ENV; \
	echo "API_BASE_URL=$$API_URL" >> $$GITHUB_ENV; \
	echo "✓ Environment variables set for GitHub Actions"


# ============================================================================
# GraphQL Validation & Schema Analysis Tool - Makefile
# ============================================================================

.PHONY: help install test validate extract clean lint format docs

# Default target
help:
	@echo "🔍 GraphQL Validation & Schema Analysis Tool"
	@echo "============================================="
	@echo ""
	@echo "📋 Available Commands:"
	@echo ""
	@echo "🎯 Core Operations:"
	@echo "  make extract          - Extract GraphQL and Pydantic models from current directory"
	@echo "  make validate         - Run surface validation on current directory"
	@echo "  make full             - Run full analysis (extract + validate + schema evolution)"
	@echo "  make dry-run          - Run dry-run mode to preview changes"
	@echo ""
	@echo "🧪 Testing:"
	@echo "  make test             - Run all tests (unit + integration)"
	@echo "  make test-unit        - Run unit tests only"
	@echo "  make test-integration - Run integration tests only"
	@echo "  make test-samples     - Test on sample files"
	@echo "  make quick-test       - Quick test of core functionality"
	@echo ""
	@echo "🔧 Development:"
	@echo "  make install          - Install dependencies"
	@echo "  make clean            - Clean up generated files"
	@echo "  make lint             - Run linting checks"
	@echo "  make format           - Format code"
	@echo ""
	@echo "📚 Documentation:"
	@echo "  make docs             - Generate documentation"
	@echo "  make readme           - Update README.md"
	@echo ""
	@echo "🎮 Interactive:"
	@echo "  make interactive      - Start interactive CLI"
	@echo "  make verify-schemas   - Verify schema loading"
	@echo ""

# ============================================================================
# Core Operations
# ============================================================================

extract:
	@echo "🔍 Extracting GraphQL and Pydantic models..."
	uv run python cli.py --extract --path .

validate:
	@echo "🔍 Running surface validation..."
	uv run python cli.py --surface-validation --path .

full:
	@echo "🔍 Running full analysis..."
	uv run python cli.py --full --old-version 2024-04 --new-version 2025-04 --path .

dry-run:
	@echo "🔍 Running dry-run mode..."
	uv run python cli.py --full --dry-run --old-version 2024-04 --new-version 2025-04 --path .

# ============================================================================
# Testing
# ============================================================================

test:
	@echo "🧪 Running all tests..."
	uv run pytest tests/ -v

test-unit:
	@echo "🧪 Running unit tests..."
	uv run pytest tests/unit/ -v

test-integration:
	@echo "🧪 Running integration tests..."
	uv run pytest tests/integration/ -v

test-samples:
	@echo "🧪 Testing on sample files..."
	@echo "Testing GraphQL file..."
	uv run python cli.py --surface-validation --path samples/test_simple.graphql
	@echo ""
	@echo "Testing Python file..."
	uv run python cli.py --surface-validation --path samples/test_fundamental_edge_cases.py
	@echo ""
	@echo "Testing schema evolution..."
	uv run python cli.py --full --old-version 2024-04 --new-version 2025-04 --path samples/test_fundamental_edge_cases.py

# ============================================================================
# Development
# ============================================================================

install:
	@echo "📦 Installing dependencies..."
	uv sync

clean:
	@echo "🧹 Cleaning up generated files..."
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -delete
	find . -type d -name "*.egg-info" -exec rm -rf {} +
	find . -type f -name ".coverage" -delete
	find . -type d -name "htmlcov" -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -exec rm -rf {} +

lint:
	@echo "🔍 Running linting checks..."
	uv run ruff check .
	uv run ruff format --check .

format:
	@echo "🎨 Formatting code..."
	uv run ruff format .
	uv run ruff check --fix .

# ============================================================================
# Documentation
# ============================================================================

docs:
	@echo "📚 Generating documentation..."
	@echo "Documentation is in README.md"

readme:
	@echo "📝 Updating README.md..."
	@echo "README.md is up to date"

# ============================================================================
# Interactive Operations
# ============================================================================

interactive:
	@echo "🎮 Starting interactive CLI..."
	uv run python cli.py

verify-schemas:
	@echo "🔍 Verifying schema loading..."
	uv run python cli.py --verify-schemas --old-version 2024-04 --new-version 2025-04

# ============================================================================
# Quick Tests
# ============================================================================

quick-test:
	@echo "⚡ Running quick tests..."
	@echo "1. Testing extraction..."
	uv run python extractor.py --path samples/test_simple.graphql --print
	@echo ""
	@echo "2. Testing surface validation..."
	uv run python cli.py --surface-validation --path samples/test_simple.graphql
	@echo ""
	@echo "3. Testing schema evolution..."
	uv run python cli.py --full --old-version 2024-04 --new-version 2025-04 --path samples/test_fundamental_edge_cases.py

# ============================================================================
# Development Workflow
# ============================================================================

dev-setup: install
	@echo "🚀 Development environment setup complete!"

dev-test: clean test
	@echo "✅ Development tests complete!"

dev-validate: format lint test
	@echo "✅ Development validation complete!"

# ============================================================================
# Utility Commands
# ============================================================================

check-deps:
	@echo "📦 Checking dependencies..."
	uv pip list

update-deps:
	@echo "📦 Updating dependencies..."
	uv pip install --upgrade -r requirements.txt

analyze-schema:
	@echo "🔍 Analyzing schema differences..."
	cd samples && uv run python analyze_schema_diff_tokens.py

# ============================================================================
# Examples
# ============================================================================

example-extract:
	@echo "📝 Example: Extract from specific path..."
	uv run python cli.py --extract --path apis/

example-validate:
	@echo "📝 Example: Validate specific file..."
	uv run python cli.py --surface-validation --path samples/test_fundamental_edge_cases.py

example-full:
	@echo "📝 Example: Full analysis with custom versions..."
	uv run python cli.py --full --old-version 2024-04 --new-version 2025-04 --path samples/

example-dry-run:
	@echo "📝 Example: Dry run with suggestions..."
	uv run python cli.py --full --dry-run --old-version 2024-04 --new-version 2025-04 --path samples/

# ============================================================================
# Helpers
# ============================================================================

version:
	@echo "📋 Tool Version Information:"
	@echo "Python: $(shell python --version)"
	@echo "UV: $(shell uv --version)"
	@echo "GraphQL Core: $(shell uv run python -c 'import graphql; print(graphql.__version__)')"

status:
	@echo "📊 Current Status:"
	@printf "Files in samples: %d\n" $(shell ls samples/ | wc -l)
	@printf "Test files: %d\n" $(shell find tests/ -name "*.py" | wc -l)
	@printf "Python files: %d\n" $(shell find . -name "*.py" | wc -l)
	@printf "GraphQL files: %d\n" $(shell find . -name "*.graphql" -o -name "*.gql" | wc -l)

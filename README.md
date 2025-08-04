# GraphQL Validation & Schema Analysis Tool

A comprehensive tool for validating GraphQL queries/mutations and Pydantic models against Shopify API schemas, detecting deprecated/removed/added fields, and providing syntax validation.

## 🚀 Quick Start

### Interactive Mode
```bash
uv run python cli.py
```

### Command Line Mode
```bash
# Extract GraphQL and Pydantic models
uv run python cli.py --extract --path /path/to/your/code

# Validate against schema evolution
uv run python cli.py --validate --old-version 2024-04 --new-version 2025-04 --path /path/to/your/code

# Full analysis with surface validation
uv run python cli.py --full --surface-validation --old-version 2024-04 --new-version 2025-04 --path /path/to/your/code

# Verify schema information
uv run python cli.py --verify-schemas --old-version 2024-04 --new-version 2025-04
```

## 📁 Project Structure

```
intern_project_graphql_validation_autofixer_tool/
├── cli.py                    # Main CLI interface
├── validator.py              # Core validation logic
├── extractor.py              # GraphQL and Pydantic extraction
├── loader.py                 # Schema loading and fetching
├── reporter.py               # Output formatting and reporting
├── samples/                  # Test files and examples
│   ├── test_fundamental_edge_cases.py
│   ├── test_graphql_edge_cases.graphql
│   ├── test_pydantic_edge_cases.py
│   └── ...
└── tests/                    # Unit and integration tests
    ├── unit/
    └── integration/
```

## 🔧 Core Components

### `cli.py` - Command Line Interface
The main entry point providing both interactive and command-line interfaces.

**Key Features:**
- Interactive menu with 6 operation modes
- Command-line arguments for automation
- Schema verification
- Dry-run mode for previewing changes

### `validator.py` - Core Validation Engine
Handles all validation logic including schema evolution and surface validation.

**Key Functions:**
- `check_deprecated_and_removed_fields()` - Schema evolution validation
- `check_surface_validation_no_schemas()` - Syntax validation without schemas
- `check_graphql_syntax_validation()` - GraphQL syntax checks
- `check_pydantic_validation()` - Pydantic model validation

### `extractor.py` - Content Extraction
Extracts GraphQL queries/mutations and Pydantic models from code files.

**Key Functions:**
- `extract_graphql_blocks()` - Extract GraphQL from Python strings
- `extract_pydantic_models()` - Extract Pydantic models
- `run_extraction()` - Process files and extract content

### `loader.py` - Schema Management
Handles loading and fetching Shopify GraphQL schemas.

**Key Functions:**
- `load_schemas()` - Main schema loading function
- `fetch_shopify_schemas_with_tokens()` - Load schemas using tokens
- `fetch_shopify_schemas_with_proxy()` - Load schemas using proxy URLs

### `reporter.py` - Output Formatting
Manages all output formatting and user interface messages.

**Key Classes:**
- `ValidationReporter` - Static methods for CLI output
- Global functions for error/warning reporting

## 🎯 CLI Usage

### Interactive Mode Options

When running `uv run python cli.py` without arguments, you'll see a menu with 6 options:

1. **Extract Only** - Extract GraphQL and Pydantic models
2. **Validate Only** - Run validation on existing code
3. **Full Analysis** - Extract + Validate + Schema Evolution
4. **Dry Run** - Preview changes without applying
5. **Interactive** - Step-by-step guided analysis
6. **Verify Schemas** - Load and compare schema versions

### Command Line Arguments

#### Operation Modes
```bash
--extract                    # Extract GraphQL and Pydantic models only
--validate                   # Run validation only
--full                       # Run full analysis (extract + validate)
--dry-run                    # Preview changes without applying
--interactive                # Run interactive step-by-step mode
--verify-schemas             # Load and compare schema versions
```

#### Schema Configuration
```bash
--old-version VERSION        # Old schema version (e.g., 2024-04)
--new-version VERSION        # New schema version (e.g., 2025-04)
                            # Default: 2025-04
```

#### Target and Options
```bash
--path PATH                  # Path to analyze (default: parent directory)
                            # Use '.' for current directory
                            # Use '..' for parent directory

--exclude PATTERNS          # Comma-separated patterns to exclude
                            # Example: --exclude "node_modules,venv,tests"

--surface-validation         # Enable GraphQL and Pydantic syntax validation
                            # (no schema loading required)

--schema-evolution          # Enable schema evolution checks
                            # (deprecated/removed/added fields)

--no-schema-evolution       # Disable schema evolution checks

--verbose                   # Enable verbose output with detailed errors

--verify-schemas            # Verify and display schema information
```

## 📋 Detailed Argument Explanations

### `--extract`
Extracts GraphQL queries/mutations and Pydantic models from your codebase without performing validation.

**Use cases:**
- Audit your codebase for GraphQL usage
- Count Pydantic models
- Generate documentation

**Example:**
```bash
uv run python cli.py --extract --path /path/to/your/code --verbose
```

### `--validate`
Runs validation on extracted content. Requires schema versions if using schema evolution.

**Use cases:**
- Check for deprecated/removed fields
- Validate GraphQL syntax
- Validate Pydantic models

**Example:**
```bash
uv run python cli.py --validate --old-version 2024-04 --new-version 2025-04 --path /path/to/your/code
```

### `--full`
Performs complete analysis: extraction + validation + schema evolution.

**Use cases:**
- Comprehensive code audit
- Migration planning
- Quality assurance

**Example:**
```bash
uv run python cli.py --full --surface-validation --old-version 2024-04 --new-version 2025-04 --path /path/to/your/code
```

### `--dry-run`
Shows what changes would be suggested without applying them.

**Use cases:**
- Preview migration impact
- Review suggested fixes
- Planning refactoring

**Example:**
```bash
uv run python cli.py --full --dry-run --old-version 2024-04 --new-version 2025-04 --path /path/to/your/code
```

### `--surface-validation`
Performs GraphQL and Pydantic syntax validation without loading schemas.

**What it checks:**
- GraphQL syntax errors (missing braces, invalid fragments)
- Pydantic model validation (required fields, type constraints)
- Unnamed operations
- Subscription operations
- Invalid fragment spreads

**Example:**
```bash
uv run python cli.py --surface-validation --path /path/to/your/code
```

### `--schema-evolution`
Checks for deprecated, removed, and newly added fields between schema versions.

**What it checks:**
- Fields marked as deprecated in the old schema
- Fields that exist in old schema but not in new schema (removed)
- Fields that exist in new schema but not in old schema (added)

**Example:**
```bash
uv run python cli.py --schema-evolution --old-version 2024-04 --new-version 2025-04 --path /path/to/your/code
```

### `--verify-schemas`
Loads and compares two schema versions, showing detailed statistics.

**What it shows:**
- Number of types loaded for each schema
- Field count comparison
- Schema evolution analysis:
  - Added/removed types
  - Added/removed fields
  - Deprecated fields

**Example:**
```bash
uv run python cli.py --verify-schemas --old-version 2024-04 --new-version 2025-04
```

### `--path`
Specifies the target path for analysis.

**Special values:**
- `.` - Current directory
- `..` - Parent directory (default)
- Any valid file or directory path

**Examples:**
```bash
uv run python cli.py --extract --path .                    # Current directory
uv run python cli.py --extract --path ..                   # Parent directory
uv run python cli.py --extract --path /path/to/your/code   # Specific path
uv run python cli.py --extract --path samples/test_file.py # Specific file
```

### `--exclude`
Specifies patterns to exclude from analysis.

**Default exclusions:**
- `node_modules`
- `venv`
- `tests`
- `__pycache__`
- `.git`
- `.env`

**Example:**
```bash
uv run python cli.py --extract --path . --exclude "node_modules,venv,temp"
```

### `--verbose`
Enables detailed output showing all extracted content and validation errors.

**Use cases:**
- Debugging extraction issues
- Detailed error analysis
- Development and testing

**Example:**
```bash
uv run python cli.py --extract --path . --verbose
```

## 🔍 Validation Types

### GraphQL Validation
The tool performs comprehensive GraphQL validation including:

**Schema Evolution Checks:**
- `[DEPRECATED]` - Fields marked as deprecated
- `[REMOVED]` - Fields that no longer exist
- `[ADDED]` - Newly added fields

**Syntax Validation:**
- `[GRAPHQL_VALIDATION]` - Syntax errors, missing arguments, type mismatches
- Unnamed operations
- Invalid fragment spreads
- Missing field names
- Subscription operations

### Pydantic Validation
Comprehensive Pydantic model validation including:

**Model Structure:**
- `[PYDANTIC_REQUIRED_FIELD]` - Missing required fields
- `[PYDANTIC_CONSTRAINT]` - Field constraint violations
- `[PYDANTIC_COMPLEX_TYPE]` - Complex type validation
- `[PYDANTIC_OPTIONAL]` - Optional field issues

**Validation Rules:**
- Required field validation
- Type constraint checking
- Nested model validation
- Union type validation
- Field dependencies

## 📊 Output Examples

### Schema Verification Output
```
🔍 Schema Verification
==============================
📋 Old Schema (2024-04):
   Admin: 2374 types loaded
   Storefront: 379 types loaded
📋 New Schema (2025-04):
   Admin: 2796 types loaded
   Storefront: 414 types loaded

📊 Admin Schema Comparison:
   Old: 8374 fields
   New: 9754 fields
   Difference: +1380 fields

🔍 Schema Evolution Analysis:
========================================
📈 Admin Schema Evolution:
   ➕ Added types: 522
   ➖ Removed types: 100
   ➕ Added fields: 473
   ➖ Removed fields: 124
   ⚠️  Deprecated fields: 413
```

### Validation Output
```
📊 Analysis Results
==================================================
📁 Files analyzed: 1
🔗 GraphQL blocks: 14
📋 Pydantic models: 20

⚠️  Issues found: 52
   Graphql Validation: 25
   Pydantic Validation: 27
```

### Dry Run Output
```
🧪 Dry Run Mode - Preview Changes
========================================
📋 Would apply 52 changes:

1. samples/test_fundamental_edge_cases.py:31
   Issue: [GRAPHQL_VALIDATION] Field 'customer' has sub-selection - verify it's not a scalar
   Action: Review the GraphQL query/mutation for syntax or schema issues

💡 This is a preview of suggested fixes. The tool provides suggestions but does not automatically apply changes.
```

## 🛠️ Environment Setup

### Required Environment Variables
Create a `.env` file in the project root:

```env
SHOPIFY_SHOP=your-shop-name
SHOPIFY_ADMIN_ACCESS_TOKEN=shpat_...
SHOPIFY_STOREFRONT_ACCESS_TOKEN=shpat_...
```

### Installation
```bash
# Install dependencies
uv sync

# Run tests
uv run pytest tests/

# Run the tool
uv run python cli.py
```

### Using Makefile (Recommended)
The project includes a comprehensive Makefile for easy usage:

```bash
# Show all available commands
make help

# Verify schema loading (recommended first step)
make verify-schemas

# Quick test of core functionality (fast)
make quick-test

# Run all tests
make test

# Extract GraphQL and Pydantic models
make extract

# Run surface validation
make validate

# Run full analysis with schema evolution
make full

# Preview changes without applying
make dry-run

# Start interactive CLI
make interactive
```

**Key Makefile Commands:**
- `make verify-schemas` - Verify schema loading (recommended first step)
- `make quick-test` - Fast testing of core functionality (recommended for quick checks)
- `make test-samples` - Comprehensive testing on sample files (slower but thorough)
- `make extract` - Extract from current directory
- `make validate` - Surface validation on current directory
- `make full` - Full analysis with schema evolution
- `make dry-run` - Preview suggested changes

## 🧪 Testing

### Quick Testing (Recommended)
```bash
# Fast test of core functionality
make quick-test

# Comprehensive testing on samples
make test-samples
```

### Run All Tests
```bash
uv run pytest tests/
# or
make test
```

### Run Specific Test Categories
```bash
uv run pytest tests/unit/           # Unit tests
# or
make test-unit

uv run pytest tests/integration/    # Integration tests
# or
make test-integration
```

### Test Files
The `samples/` directory contains comprehensive test files:
- `test_fundamental_edge_cases.py` - 17 fundamental edge cases
- `test_graphql_edge_cases.graphql` - GraphQL syntax edge cases
- `test_pydantic_edge_cases.py` - Pydantic model edge cases

## 🔧 Advanced Usage

### Custom Validation Rules
You can extend the validation by modifying the validation functions in `validator.py`:

- `check_graphql_syntax_validation()` - Add custom GraphQL checks
- `check_pydantic_validation()` - Add custom Pydantic checks

### Schema Loading
The tool automatically chooses the appropriate schema loading method:
- **Versions < 2024-10**: Uses tokens
- **Versions >= 2024-10**: Uses proxy URLs

### Integration with CI/CD
```bash
# Example CI script
uv run python cli.py --full --surface-validation --old-version 2024-04 --new-version 2025-04 --path . --exclude "node_modules,venv,tests"
```

## 🐛 Troubleshooting

### Common Issues

**Schema Loading Errors:**
- Check environment variables are set correctly
- Verify Shopify shop name and access tokens
- Ensure network connectivity

**Extraction Issues:**
- GraphQL queries must be in triple-quoted strings in Python files
- Pydantic models must be properly defined classes
- Check file encoding (UTF-8 recommended)

**Validation Errors:**
- Use `--verbose` for detailed error information
- Check schema versions are correct
- Verify field names match schema definitions

### Debug Mode
```bash
# Enable verbose output for debugging
uv run python cli.py --extract --path . --verbose

# Check schema loading
uv run python cli.py --verify-schemas --old-version 2024-04 --new-version 2025-04
```

## 📝 Contributing

1. Follow the existing code structure
2. Add tests for new features
3. Update documentation
4. Use `uv run` for all Python commands
5. Follow the project's linting rules

## 📄 License

This project is part of the alo-api codebase and follows the same licensing terms.

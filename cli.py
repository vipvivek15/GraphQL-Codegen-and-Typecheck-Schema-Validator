#!/usr/bin/env python3
"""
Interactive CLI for GraphQL Validation and Schema Analysis

This CLI provides a user-friendly interface for:
- Schema loading and validation
- GraphQL/Pydantic extraction and analysis
- Interactive version selection
- Dry-run functionality
- Comprehensive reporting

Usage:
    python cli.py                    # Interactive mode
    python cli.py --extract          # Extract only
    python cli.py --validate         # Validate only
    python cli.py --full             # Full analysis
    python cli.py --dry-run          # Preview changes
"""

import argparse
import os
import sys
from typing import Any, Dict, List, Tuple

# Add current directory to path for imports
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from extractor import extract_graphql_blocks, extract_pydantic_models
from loader import check_api_version_compatibility, load_schemas
from reporter import ValidationReporter, print_error
from validator import (
    check_deprecated_and_removed_fields,
    check_surface_validation,
    check_surface_validation_no_schemas,
    find_files,
)

from config import SHOPIFY_VERSION


class InteractiveCLI:
    """Interactive CLI for GraphQL validation and analysis."""

    def __init__(self):
        self.old_version = None
        self.new_version = None
        self.target_path = ".."  # Default to parent directory (main alo-api directory)
        # Default exclusions for common directories that shouldn't be validated
        self.default_exclusions = [
            "graphql_validator_tool",
            "intern_project_graphql_validation_autofixer_tool",
            "venv",
            ".venv",
            "__pycache__",
            ".git",
            "node_modules",
            ".pytest_cache",
            ".mypy_cache",
            ".ruff_cache",
            ".github",
            "doc",
            "load_tests",
            "pyright-sample",
            "shopify-graphql-test",
            "volume",
            "tests",
            "openapi",
            "schema",
            "scripts",
        ]
        self.exclude_patterns = []
        self.surface_validation = False
        self.schema_evolution = True
        self.dry_run = False
        self.verbose = False

    def print_banner(self):
        """Print the CLI banner."""
        ValidationReporter.print_banner()

    def get_user_input(self, prompt: str, default: str = "", validator=None) -> str:
        """Get user input with validation."""
        while True:
            if default:
                user_input = input(f"{prompt} [{default}]: ").strip()
                if not user_input:
                    user_input = default
            else:
                user_input = input(f"{prompt}: ").strip()

            if validator and not validator(user_input):
                print_error(f"Invalid input: {user_input}")
                continue

            return user_input

    def select_operation_mode(self) -> str:
        """Let user select the operation mode."""
        ValidationReporter.print_operation_mode_selection()

        while True:
            ValidationReporter.print_choice_prompt()
            choice = input().strip()
            if choice in ["1", "2", "3", "4", "5"]:
                return choice
            ValidationReporter.print_invalid_choice()

    def get_schema_versions(self) -> Tuple[str, str]:
        """Get old and new schema versions interactively."""
        ValidationReporter.print_schema_version_selection()

        # Get old version
        old_version = self.get_user_input(
            "Enter old schema version (e.g., 2024-04)",
            default="2024-04",
            validator=check_api_version_compatibility,
        )

        # Get new version
        new_version = self.get_user_input(
            "Enter new schema version (e.g., 2025-04)",
            default=SHOPIFY_VERSION,
            validator=check_api_version_compatibility,
        )

        return old_version, new_version

    def get_target_path(self) -> str:
        """Get target path for analysis."""
        ValidationReporter.print_target_path_selection()

        current_dir = os.getcwd()
        # Default to parent directory (main alo-api directory)
        parent_dir = os.path.dirname(current_dir)
        target = self.get_user_input(
            "Enter path to analyze (use '.' for current directory, '..' for parent directory, or relative paths like 'samples/' or '../apis/')",
            default="..",
        )

        # Handle "." for current directory and ".." for parent directory
        if target == ".":
            target = current_dir
        elif target == "..":
            target = parent_dir
        else:
            # Handle relative paths by converting to absolute path
            target = os.path.abspath(target)

        if not os.path.exists(target):
            print_error(f"Path does not exist: {target}")
            return self.get_target_path()

        return target

    def _validate_yn_input(self, value: str) -> bool:
        """Validate that input is 'y' or 'n'."""
        return value.lower() in ["y", "n"]

    def get_validation_options(self) -> Dict[str, bool]:
        """Get validation options interactively."""
        ValidationReporter.print_validation_options()

        options = {}

        # Schema evolution - default to False for validation-focused options
        schema_evolution = (
            self.get_user_input(
                "Check for deprecated/removed/added fields? [y/n]",
                validator=self._validate_yn_input,
            )
            .strip()
            .lower()
        )
        options["schema_evolution"] = schema_evolution == "y"

        # Surface validation - default to True for validation-focused options
        surface_validation = (
            self.get_user_input(
                "Run surface-level GraphQL/Pydantic validation? [y/n]",
                validator=self._validate_yn_input,
            )
            .strip()
            .lower()
        )
        options["surface_validation"] = surface_validation == "y"

        # Verbose mode
        verbose = (
            self.get_user_input(
                "Enable verbose output? [y/n]", validator=self._validate_yn_input
            )
            .strip()
            .lower()
        )
        options["verbose"] = verbose == "y"

        return options

    def load_schemas_interactive(self) -> Tuple[Any, Any, Any, Any]:
        """Load schemas with progress indication."""
        ValidationReporter.print_schema_loading_start(
            self.old_version, self.new_version
        )

        try:
            # Load old schemas
            old_admin_schema, old_storefront_schema = load_schemas(self.old_version)
            # Load new schemas
            new_admin_schema, new_storefront_schema = load_schemas(self.new_version)

            ValidationReporter.print_schema_loading_success()

            # Verify schemas if requested
            if hasattr(self, "verify_schemas") and self.verify_schemas:
                self.verify_schema_info(
                    old_admin_schema,
                    old_storefront_schema,
                    new_admin_schema,
                    new_storefront_schema,
                )

            return (
                old_admin_schema,
                old_storefront_schema,
                new_admin_schema,
                new_storefront_schema,
            )

        except Exception as e:
            print_error(f"Failed to load schemas: {e}")
            sys.exit(1)

    def verify_schema_info(
        self,
        old_admin_schema: Any,
        old_storefront_schema: Any,
        new_admin_schema: Any,
        new_storefront_schema: Any,
    ) -> None:
        """Verify and display schema information."""
        ValidationReporter.print_schema_verification_header()

        # Old schemas
        ValidationReporter.print_old_schema_header(self.old_version)
        if old_admin_schema:
            admin_types = (
                len(old_admin_schema.type_map)
                if hasattr(old_admin_schema, "type_map")
                else 0
            )
            ValidationReporter.print_admin_schema_status(admin_types, True)
        else:
            ValidationReporter.print_admin_schema_status(0, False)

        if old_storefront_schema:
            storefront_types = (
                len(old_storefront_schema.type_map)
                if hasattr(old_storefront_schema, "type_map")
                else 0
            )
            ValidationReporter.print_storefront_schema_status(storefront_types, True)
        else:
            ValidationReporter.print_storefront_schema_status(0, False)

        # New schemas
        ValidationReporter.print_new_schema_header(self.new_version)
        if new_admin_schema:
            admin_types = (
                len(new_admin_schema.type_map)
                if hasattr(new_admin_schema, "type_map")
                else 0
            )
            ValidationReporter.print_admin_schema_status(admin_types, True)
        else:
            ValidationReporter.print_admin_schema_status(0, False)

        if new_storefront_schema:
            storefront_types = (
                len(new_storefront_schema.type_map)
                if hasattr(new_storefront_schema, "type_map")
                else 0
            )
            ValidationReporter.print_storefront_schema_status(storefront_types, True)
        else:
            ValidationReporter.print_storefront_schema_status(0, False)

        # Schema comparison
        if old_admin_schema and new_admin_schema:
            old_admin_fields = sum(
                len(getattr(t, "fields", {}))
                for t in old_admin_schema.type_map.values()
                if hasattr(t, "fields")
            )
            new_admin_fields = sum(
                len(getattr(t, "fields", {}))
                for t in new_admin_schema.type_map.values()
                if hasattr(t, "fields")
            )
            ValidationReporter.print_admin_comparison(
                old_admin_fields, new_admin_fields
            )

        if old_storefront_schema and new_storefront_schema:
            old_storefront_fields = sum(
                len(getattr(t, "fields", {}))
                for t in old_storefront_schema.type_map.values()
                if hasattr(t, "fields")
            )
            new_storefront_fields = sum(
                len(getattr(t, "fields", {}))
                for t in new_storefront_schema.type_map.values()
                if hasattr(t, "fields")
            )
            ValidationReporter.print_storefront_comparison(
                old_storefront_fields, new_storefront_fields
            )

        # Analyze schema evolution details
        ValidationReporter.print_schema_evolution_analysis_header()

        # Admin schema evolution
        if old_admin_schema and new_admin_schema:
            admin_stats = self._analyze_schema_evolution(
                old_admin_schema, new_admin_schema, "Admin"
            )
            ValidationReporter.print_schema_evolution_summary("Admin", admin_stats)

        # Storefront schema evolution
        if old_storefront_schema and new_storefront_schema:
            storefront_stats = self._analyze_schema_evolution(
                old_storefront_schema, new_storefront_schema, "Storefront"
            )
            ValidationReporter.print_schema_evolution_summary(
                "Storefront", storefront_stats
            )

    def run_extraction(self) -> List[Dict[str, Any]]:
        """Run extraction on target path."""
        print(f"🔍 Scanning files in {self.target_path}...")

        # Find all relevant files
        all_exclusions = self.default_exclusions + self.exclude_patterns
        files = find_files(self.target_path, all_exclusions)

        print(f"📁 Found {len(files)} files to process")

        if not files:
            print("❌ No files found to process")
            return []

        # Limit files for demo purposes to prevent hanging
        if len(files) > 500:
            print(
                f"⚠️  Limiting to first 500 files to prevent hanging (found {len(files)} total)"
            )
            files = files[:500]

        results = []
        for i, file_path in enumerate(files):
            try:
                # Extract GraphQL and Pydantic content
                with open(file_path, "r", encoding="utf-8") as f:
                    source = f.read()

                # Extract GraphQL blocks
                graphql_blocks = extract_graphql_blocks(source)

                # Extract Pydantic models
                pydantic_models = extract_pydantic_models(source)

                if graphql_blocks or pydantic_models:
                    results.append(
                        {
                            "file": file_path,
                            "graphql": graphql_blocks,
                            "pydantic_models": pydantic_models,
                        }
                    )

            except Exception as e:
                if self.verbose:
                    print(f"⚠️  Error processing {file_path}: {e}")
                continue

        print(f"✅ Extraction complete: {len(results)} files with content found")
        return results

    def _analyze_schema_evolution(
        self, old_schema: Any, new_schema: Any, schema_name: str
    ) -> Dict[str, int]:
        """Analyze schema evolution between two versions."""
        # Get all types from both schemas
        old_types = set(old_schema.type_map.keys())
        new_types = set(new_schema.type_map.keys())

        # Find removed and added types
        removed_types = old_types - new_types
        added_types = new_types - old_types

        # Analyze field differences for common types
        common_types = old_types & new_types
        removed_fields = 0
        added_fields = 0
        deprecated_fields = 0

        for type_name in common_types:
            old_fields = self._get_type_fields(old_schema, type_name)
            new_fields = self._get_type_fields(new_schema, type_name)

            type_removed_fields = old_fields - new_fields
            type_added_fields = new_fields - old_fields

            removed_fields += len(type_removed_fields)
            added_fields += len(type_added_fields)

            # Check for deprecated fields in old schema
            old_deprecated = self._get_deprecated_fields(old_schema, type_name)
            deprecated_fields += len(old_deprecated)

        return {
            "removed_types": len(removed_types),
            "added_types": len(added_types),
            "removed_fields": removed_fields,
            "added_fields": added_fields,
            "deprecated_fields": deprecated_fields,
        }

    def _get_type_fields(self, schema: Any, type_name: str) -> set:
        """Get all field names for a given type in a schema."""
        schema_type = schema.get_type(type_name)
        if not schema_type or not hasattr(schema_type, "fields"):
            return set()
        return set(schema_type.fields.keys())

    def _get_deprecated_fields(self, schema: Any, type_name: str) -> Dict[str, str]:
        """Get deprecated fields and their reasons for a given type in a schema."""
        schema_type = schema.get_type(type_name)
        if not schema_type or not hasattr(schema_type, "fields"):
            return {}

        deprecated_fields = {}
        for field_name, field in schema_type.fields.items():
            is_deprecated = getattr(field, "is_deprecated", False)
            deprecation_reason = getattr(field, "deprecation_reason", None)
            if is_deprecated or deprecation_reason:
                deprecated_fields[field_name] = deprecation_reason or "Deprecated"

        return deprecated_fields

    def run_validation(
        self, schemas: Tuple[Any, Any, Any, Any], results: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Run validation on extracted results."""
        warnings = []

        if not results:
            return warnings

        print("🔍 Running validation...")

        for i, result in enumerate(results):
            file_path = result.get("file", "unknown")
            file_warnings = []

            # Schema-based validation (deprecated/removed/added)
            if self.schema_evolution and schemas:
                (
                    old_admin_schema,
                    old_storefront_schema,
                    new_admin_schema,
                    new_storefront_schema,
                ) = schemas
                schema_warnings = check_deprecated_and_removed_fields(
                    file_path,
                    old_admin_schema,
                    old_storefront_schema,
                    new_admin_schema,
                    new_storefront_schema,
                )
                file_warnings.extend(schema_warnings)

            # Surface validation (GraphQL/Pydantic syntax) - only run when surface_validation is True
            if self.surface_validation:
                if schemas:
                    # Pass schemas directly to check_surface_validation for comprehensive validation
                    old_admin_schema, old_storefront_schema, new_admin_schema, new_storefront_schema = schemas
                    surface_warnings = check_surface_validation(file_path, old_admin_schema, old_storefront_schema, new_admin_schema, new_storefront_schema)
                    file_warnings.extend(surface_warnings)
                else:
                    # Surface validation without schemas (pattern-based only)
                    surface_warnings = check_surface_validation_no_schemas(file_path)
                    file_warnings.extend(surface_warnings)

            warnings.extend(file_warnings)

        print("✅ Validation complete")
        return warnings

    def display_results(
        self,
        results: List[Dict[str, Any]],
        warnings: List[Dict[str, Any]],
        show_suggestions: bool = True,
    ):
        """Display extraction and validation results."""
        if not results:
            ValidationReporter.print_no_files_found()
            return

        # Show extraction results
        total_files = len(results)
        total_graphql = sum(len(result["graphql"]) for result in results)
        total_pydantic = sum(len(result.get("pydantic_models", [])) for result in results)

        ValidationReporter.print_extraction_summary(
            total_files, total_graphql, total_pydantic
        )

        # Show detailed extraction results using the existing reporter function
        from reporter import print_results

        print_results(results)

        # Show validation results if any
        if warnings:
            ValidationReporter.print_validation_summary(len(warnings))

            # Show suggestions only if requested
            if show_suggestions:
                suggestions = self.suggest_fixes(warnings)
                ValidationReporter.print_suggestions_header()
                for suggestion in suggestions:
                    ValidationReporter.print_suggestion_details(suggestion)
        else:
            ValidationReporter.print_no_issues_found()

        # Show final summary at the end
        # Count GraphQL by type
        query_count = 0
        mutation_count = 0
        subscription_count = 0
        fragment_count = 0

        for result in results:
            for block in result.get("graphql", []):
                block_type = block.get("type", "").lower()
                if block_type == "query":
                    query_count += 1
                elif block_type == "mutation":
                    mutation_count += 1
                elif block_type == "subscription":
                    subscription_count += 1
                elif block_type == "fragment":
                    fragment_count += 1

        ValidationReporter.print_extraction_summary_detailed(
            total_files,
            total_pydantic,
            query_count,
            mutation_count,
            subscription_count,
            fragment_count,
            total_graphql,
        )

    def display_validation_only(
        self, results: List[Dict[str, Any]], warnings: List[Dict[str, Any]]
    ):
        """Display validation results without suggestions (for Option 3)."""
        if not results:
            ValidationReporter.print_no_files_found()
            return

        # Don't show extraction details for validation-only mode
        # total_files = len(results)
        # total_graphql = sum(len(result['graphql']) for result in results)
        # total_pydantic = sum(len(result['pydantic_models']) for result in results)
        # ValidationReporter.print_extraction_summary(total_files, total_graphql, total_pydantic)

        if warnings:
            ValidationReporter.print_validation_summary(len(warnings))
            categories = self.categorize_issues(warnings)
            ValidationReporter.print_category_summary(categories)
            self.display_issues_by_category(warnings)
        else:
            ValidationReporter.print_no_issues_found()

    def categorize_issues(self, warnings: List[Dict[str, Any]]) -> Dict[str, int]:
        """Categorize issues by type."""
        categories = {
            "DEPRECATED": 0,
            "REMOVED": 0,
            "ADDED": 0,
            "GRAPHQL_VALIDATION": 0,
            "PYDANTIC_CONSTRAINT": 0,
            "PYDANTIC_REQUIRED_FIELD": 0,
            "PYDANTIC_COMPLEX_TYPE": 0,
            "PYDANTIC_OPTIONAL": 0,
            "OTHER": 0,
        }

        for warning in warnings:
            message = warning.get("message", "")
            if "[DEPRECATED]" in message:
                categories["DEPRECATED"] += 1
            elif "[REMOVED]" in message:
                categories["REMOVED"] += 1
            elif "[ADDED]" in message:
                categories["ADDED"] += 1
            elif "[GRAPHQL_VALIDATION]" in message or "[GRAPHQL_NON_EXISTENT_FIELD]" in message or "[GRAPHQL_INVALID_ARGUMENT]" in message or "[GRAPHQL_INVALID_ID]" in message or "[GRAPHQL_INVALID_DIRECTIVE]" in message or "[GRAPHQL_INVALID_FRAGMENT]" in message or "[GRAPHQL_UNNAMED_OPERATION]" in message or "[GRAPHQL_SYNTAX]" in message:
                categories["GRAPHQL_VALIDATION"] += 1
            elif "[PYDANTIC_CONSTRAINT]" in message:
                categories["PYDANTIC_CONSTRAINT"] += 1
            elif "[PYDANTIC_REQUIRED_FIELD]" in message:
                categories["PYDANTIC_REQUIRED_FIELD"] += 1
            elif "[PYDANTIC_COMPLEX_TYPE]" in message:
                categories["PYDANTIC_COMPLEX_TYPE"] += 1
            elif "[PYDANTIC_OPTIONAL]" in message:
                categories["PYDANTIC_OPTIONAL"] += 1
            else:
                categories["OTHER"] += 1

        return categories

    def display_issues_by_category(self, warnings: List[Dict[str, Any]]):
        """Display issues grouped by category."""
        categories = {
            "DEPRECATED": [],
            "REMOVED": [],
            "ADDED": [],
            "GRAPHQL_VALIDATION": [],
            "PYDANTIC_CONSTRAINT": [],
            "PYDANTIC_REQUIRED_FIELD": [],
            "PYDANTIC_COMPLEX_TYPE": [],
            "PYDANTIC_OPTIONAL": [],
            "OTHER": [],
        }

        for warning in warnings:
            message = warning.get("message", "")
            if "[DEPRECATED]" in message:
                categories["DEPRECATED"].append(warning)
            elif "[REMOVED]" in message:
                categories["REMOVED"].append(warning)
            elif "[ADDED]" in message:
                categories["ADDED"].append(warning)
            elif "[GRAPHQL_VALIDATION]" in message or "[GRAPHQL_NON_EXISTENT_FIELD]" in message or "[GRAPHQL_INVALID_ARGUMENT]" in message or "[GRAPHQL_INVALID_ID]" in message or "[GRAPHQL_INVALID_DIRECTIVE]" in message or "[GRAPHQL_INVALID_FRAGMENT]" in message or "[GRAPHQL_UNNAMED_OPERATION]" in message or "[GRAPHQL_SYNTAX]" in message:
                categories["GRAPHQL_VALIDATION"].append(warning)
            elif "[PYDANTIC_CONSTRAINT]" in message:
                categories["PYDANTIC_CONSTRAINT"].append(warning)
            elif "[PYDANTIC_REQUIRED_FIELD]" in message:
                categories["PYDANTIC_REQUIRED_FIELD"].append(warning)
            elif "[PYDANTIC_COMPLEX_TYPE]" in message:
                categories["PYDANTIC_COMPLEX_TYPE"].append(warning)
            elif "[PYDANTIC_OPTIONAL]" in message:
                categories["PYDANTIC_OPTIONAL"].append(warning)
            else:
                categories["OTHER"].append(warning)

        # Display each category
        for category, issues in categories.items():
            if issues:
                if self.verbose:
                    print(f"\n📋 {category} Issues ({len(issues)}):")
                    for issue in issues:
                        file_path = issue.get("file", "?")
                        line = issue.get("line", issue.get("start_line", "?"))
                        column = issue.get("column", issue.get("start_col", "?"))
                        message = issue.get("message", "?")
                        print(f"   {file_path}:{line}:{column} - {message}")
                else:
                    print(
                        f"   {len(issues)} {category.lower()} issues found (use --verbose to see details)"
                    )

    def suggest_fixes(self, warnings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Suggest fixes for found issues."""
        suggestions = []

        for warning in warnings:
            message = warning.get("message", "")
            file_path = warning.get("file", "")
            line = warning.get("line", "")
            column = warning.get("column", "")

            suggestion = {
                "file": file_path,
                "line": line,
                "column": column,
                "issue": message,
                "fix": self.generate_fix_suggestion(message),
            }
            suggestions.append(suggestion)

        # Sort suggestions by line number for better readability
        suggestions.sort(
            key=lambda x: (x["file"], x["line"] if isinstance(x["line"], int) else 0)
        )

        return suggestions

    def generate_fix_suggestion(self, message: str) -> str:
        """Generate fix suggestion based on error message."""
        if "[DEPRECATED]" in message:
            if "email" in message and "defaultEmailAddress.emailAddress" in message:
                return "Replace 'email' field with 'defaultEmailAddress.emailAddress'"
            elif "emailMarketingConsent" in message:
                return "Replace 'emailMarketingConsent' with 'defaultEmailAddress.marketingState', 'defaultEmailAddress.marketingOptInLevel', etc."
            elif "userErrors" in message:
                return "Replace 'userErrors' with 'customerUserErrors'"
            else:
                return "Replace with the suggested alternative field from the deprecation message"
        elif "[REMOVED]" in message:
            return "Remove this field as it no longer exists in the schema"
        elif "[ADDED]" in message:
            return "This field is new - consider if you need to handle it"
        elif "[GRAPHQL_VALIDATION]" in message:
            if "has sub-selection" in message:
                return "Remove sub-selection from scalar field or add sub-selection to object field"
            elif "Invalid syntax" in message:
                return "Fix GraphQL syntax error - check for missing field names or invalid structure"
            elif "Inline fragment" in message:
                return "Verify inline fragment type compatibility with parent context"
            elif "Operation must have a name" in message:
                return "Add a name to the GraphQL operation"
            else:
                return "Review the GraphQL query/mutation for syntax or schema issues"
        elif "[PYDANTIC_CONSTRAINT]" in message:
            return "Review and verify the constraint values are appropriate for your use case"
        elif "[PYDANTIC_REQUIRED_FIELD]" in message:
            return "Add default value or make field optional if appropriate"
        elif "[PYDANTIC_COMPLEX_TYPE]" in message:
            return "Verify type compatibility and ensure proper imports"
        elif "[PYDANTIC_OPTIONAL]" in message:
            return "Consider adding a default value for optional fields"
        elif "[MISSING_REQUIRED_ARG]" in message:
            return "Add the required argument to the field"
        elif "[TYPE_MISMATCH]" in message:
            return "Fix the data type to match the schema definition"
        else:
            return "Review the code for the specific issue mentioned in the error"

    def run_dry_run(self, suggestions: List[Dict[str, Any]]):
        """Run dry-run mode to preview changes."""
        ValidationReporter.print_dry_run_header()

        if not suggestions:
            ValidationReporter.print_dry_run_summary([])
            return

        ValidationReporter.print_dry_run_summary(suggestions)

        for i, suggestion in enumerate(suggestions, 1):
            ValidationReporter.print_dry_run_suggestion(i, suggestion)

        ValidationReporter.print_dry_run_footer()

    def run_extract_only(self):
        """Run extraction only and display results."""
        results = self.run_extraction()

        if not results:
            print("❌ No GraphQL or Pydantic content found")
            return

        # Calculate totals
        total_graphql_blocks = sum(len(result.get("graphql", [])) for result in results)
        total_pydantic_models = sum(
            len(result.get("pydantic_models", [])) for result in results
        )

        # Count by type
        query_count = sum(
            1
            for result in results
            for block in result.get("graphql", [])
            if block.get("type") == "query"
        )
        mutation_count = sum(
            1
            for result in results
            for block in result.get("graphql", [])
            if block.get("type") == "mutation"
        )
        subscription_count = sum(
            1
            for result in results
            for block in result.get("graphql", [])
            if block.get("type") == "subscription"
        )
        fragment_count = sum(
            1
            for result in results
            for block in result.get("graphql", [])
            if block.get("type") == "fragment"
        )

        # Show detailed content
        print("\n📄 Extracted Content:")
        for result in results:
            file_path = result.get("file", "unknown")
            graphql_blocks = result.get("graphql", [])
            pydantic_models = result.get("pydantic_models", [])

            if graphql_blocks or pydantic_models:
                print(f"\n--- {file_path} ---")

                if graphql_blocks:
                    print("GraphQL Blocks:")
                    for i, block in enumerate(graphql_blocks, 1):
                        block_type = block.get("type", "unknown")
                        block_name = block.get("name", "unnamed")
                        start_line = block.get("start_line", "?")
                        end_line = block.get("end_line", "?")

                        print(f"  {i}. {block_type.upper()}: {block_name}")
                        print(f"     Lines: {start_line}-{end_line}")

                        # Show the actual GraphQL content
                        raw_content = block.get("raw", "")
                        if raw_content:
                            lines = raw_content.splitlines()
                            if len(lines) > 10:
                                print("     Content (first 10 lines):")
                                for line in lines[:10]:
                                    print(f"       {line}")
                                print(f"     ... and {len(lines) - 10} more lines")
                            else:
                                print("     Content:")
                                for line in lines:
                                    print(f"       {line}")
                        print()

                if pydantic_models:
                    print("Pydantic Models:")
                    for i, model in enumerate(pydantic_models, 1):
                        model_name = model.get("model_name", "unknown")
                        start_line = model.get("start_line", "?")
                        end_line = model.get("end_line", "?")

                        print(f"  {i}. {model_name}")
                        print(f"     Lines: {start_line}-{end_line}")

                        # Show the actual Pydantic model content
                        raw_content = model.get("raw", "")
                        if raw_content:
                            lines = raw_content.splitlines()
                            if len(lines) > 8:
                                print("     Content (first 8 lines):")
                                for line in lines[:8]:
                                    print(f"       {line}")
                                print(f"     ... and {len(lines) - 8} more lines")
                            else:
                                print("     Content:")
                                for line in lines:
                                    print(f"       {line}")
                        print()

        # Show summary at the end
        print("\n📊 Extraction Summary:")
        print(f"   📁 Files with content: {len(results)}")
        print(f"   🔗 GraphQL queries: {query_count}")
        print(f"   🔄 GraphQL mutations: {mutation_count}")
        print(f"   📡 GraphQL subscriptions: {subscription_count}")
        print(f"   🧩 GraphQL fragments: {fragment_count}")
        print(f"   📋 Pydantic models: {total_pydantic_models}")

    def run_interactive_mode(self):
        """Run interactive mode with menu loop."""
        while True:
            mode = self.select_operation_mode()

            if mode == "1":  # Verify schemas
                self.old_version, self.new_version = self.get_schema_versions()
                schemas = self.load_schemas_interactive()
                self.verify_schema_info(*schemas)

            elif mode == "2":  # Schema analysis
                self.run_schema_analysis()

            elif mode == "3":  # Extract only
                self.target_path = self.get_target_path()
                self.run_extract_only()

            elif mode == "4":  # Full analysis
                self.target_path = self.get_target_path()
                options = self.get_validation_options()

                self.schema_evolution = options.get("schema_evolution", False)
                self.surface_validation = options.get("surface_validation", False)
                self.verbose = options.get("verbose", False)

                # Only get schema versions and load schemas if schema evolution is enabled
                schemas = None
                if self.schema_evolution:
                    self.old_version, self.new_version = self.get_schema_versions()
                    schemas = self.load_schemas_interactive()

                # Run extraction to get file list, but don't show results
                results = self.run_extraction()
                warnings = self.run_validation(schemas, results)

                # Show only validation results and suggestions, skip extraction details
                if warnings:
                    ValidationReporter.print_validation_summary(len(warnings))
                    # Show issues by category (respects verbose setting)
                    self.display_issues_by_category(warnings)
                    suggestions = self.suggest_fixes(warnings)
                    if self.verbose:
                        # Show detailed suggestions only when verbose is enabled
                        ValidationReporter.print_suggestions_header()
                        for suggestion in suggestions:
                            ValidationReporter.print_suggestion_details(suggestion)
                    else:
                        # Show only summary when verbose is disabled
                        ValidationReporter.print_suggestions_summary(
                            suggestions, self.verbose
                        )
                else:
                    ValidationReporter.print_no_issues_found()

            elif mode == "5":  # Quit
                ValidationReporter.print_goodbye()
                return

            # Ask if user wants to return to main menu
            ValidationReporter.print_menu_return_prompt()
            choice = input().strip().lower()
            if choice not in ["y", "yes"]:
                ValidationReporter.print_goodbye()
                return
            ValidationReporter.print_empty_line()

    def run_step_by_step(self):
        """Run step-by-step guided analysis."""
        self.print_banner()
        ValidationReporter.print_interactive_header()

        # Step 1: Target path
        ValidationReporter.print_step_header(1, "Target Path")
        self.target_path = self.get_target_path()

        # Step 2: Validation options
        ValidationReporter.print_step_header(2, "Validation Options")
        options = self.get_validation_options()
        self.schema_evolution = options.get(
            "schema_evolution", False
        )  # Default to False for validation-focused options
        self.surface_validation = options.get("surface_validation", False)
        self.verbose = options.get("verbose", False)

        # Step 3: Schema versions (only if schema evolution is enabled)
        if self.schema_evolution:
            ValidationReporter.print_step_header(3, "Schema Versions")
            self.old_version, self.new_version = self.get_schema_versions()

            # Step 4: Loading schemas
            ValidationReporter.print_step_header(4, "Loading Schemas")
            schemas = self.load_schemas_interactive()
        else:
            ValidationReporter.print_skipping_schema_evolution()
            schemas = None

        # Step 5: Extraction
        ValidationReporter.print_step_header(5, "Extraction")
        results = self.run_extraction()

        # Step 6: Validation
        ValidationReporter.print_step_header(6, "Validation")
        warnings = self.run_validation(schemas, results)

        # Step 7: Results
        ValidationReporter.print_step_header(7, "Results")
        total_files = len(results)
        total_graphql = sum(len(result["graphql"]) for result in results)
        total_pydantic = sum(len(result.get("pydantic_models", [])) for result in results)
        ValidationReporter.print_extraction_summary(
            total_files, total_graphql, total_pydantic
        )
        ValidationReporter.print_validation_summary(len(warnings))
        if warnings:
            categories = self.categorize_issues(warnings)
            ValidationReporter.print_category_summary(categories)
            self.display_issues_by_category(warnings)
        else:
            ValidationReporter.print_no_issues_found()

        # Step 8: Suggestions (only if there are warnings)
        if warnings:
            ValidationReporter.print_step_header(8, "Suggestions")
            suggestions = self.suggest_fixes(warnings)

            # Show detailed suggestions with proper input handling
            try:
                show_details = self.get_user_input(
                    "Show detailed fix suggestions? (y/n)", default="n"
                )
                if show_details.lower() == "y":
                    ValidationReporter.print_suggestions_header()
                    for suggestion in suggestions:
                        ValidationReporter.print_suggestion_details(suggestion)
            except (EOFError, KeyboardInterrupt):
                ValidationReporter.print_skipping_suggestions()

        ValidationReporter.print_analysis_complete()

    def run_schema_analysis(self):
        """Run detailed schema analysis showing added/removed/deprecated fields."""
        print("\n🔍 Schema Analysis Mode")
        print("=" * 50)
        
        # Always get schema versions for schema analysis (don't reuse previous values)
        self.old_version, self.new_version = self.get_schema_versions()
        
        # Load schemas
        schemas = self.load_schemas_interactive()
        old_admin_schema, old_storefront_schema, new_admin_schema, new_storefront_schema = schemas
        
        print(f"\n📊 Analyzing schema differences between {self.old_version} and {self.new_version}")
        print("=" * 70)
        
        # Capture the analysis output
        analysis_output = []
        analysis_output.append(f"📊 Schema Analysis Report")
        analysis_output.append(f"Comparing {self.old_version} → {self.new_version}")
        analysis_output.append("=" * 70)
        
        # Analyze Admin schema
        print("\n🏢 Admin Schema Analysis")
        print("-" * 30)
        admin_output = self._analyze_schema_detailed(old_admin_schema, new_admin_schema, "Admin")
        analysis_output.extend(admin_output)
        
        # Analyze Storefront schema
        print("\n🛍️  Storefront Schema Analysis")
        print("-" * 35)
        storefront_output = self._analyze_schema_detailed(old_storefront_schema, new_storefront_schema, "Storefront")
        analysis_output.extend(storefront_output)
        
        analysis_output.append("\n✅ Schema analysis complete!")
        print("\n✅ Schema analysis complete!")
        
        # Ask if user wants to save the output
        save_output = self.get_user_input(
            "\n💾 Would you like to save this analysis to a file? (y/n): ",
            validator=self._validate_yn_input
        )
        
        if save_output.lower() == 'y':
            filename = self.get_user_input(
                "📁 Enter filename (press Enter for default 'schema_analysis.txt'): "
            )
            # Use default if empty
            if not filename.strip():
                filename = "schema_analysis.txt"
            try:
                with open(filename, 'w', encoding='utf-8') as f:
                    f.write('\n'.join(analysis_output))
                print(f"✅ Analysis saved to: {filename}")
            except Exception as e:
                print(f"❌ Error saving file: {e}")

    def _analyze_schema_detailed(self, old_schema: Any, new_schema: Any, schema_name: str) -> List[str]:
        """Analyze detailed differences between two schemas and return output lines."""
        output_lines = []
        output_lines.append(f"\n🏢 {schema_name} Schema Analysis")
        output_lines.append("-" * 30)
        
        # Get all types from both schemas
        old_types = set(old_schema.type_map.keys())
        new_types = set(new_schema.type_map.keys())

        # Find removed types
        removed_types = old_types - new_types
        if removed_types:
            output_lines.append(f"\n❌ Removed types in {schema_name}:")
            for type_name in sorted(removed_types):
                output_lines.append(f"  - {type_name}")

        # Find added types
        added_types = new_types - old_types
        if added_types:
            output_lines.append(f"\n✅ Added types in {schema_name}:")
            for type_name in sorted(added_types):
                output_lines.append(f"  - {type_name}")

        # Analyze field differences for common types
        common_types = old_types & new_types
        removed_fields = []
        added_fields = []
        deprecated_fields = []

        for type_name in sorted(common_types):
            old_fields = self._get_type_fields(old_schema, type_name)
            new_fields = self._get_type_fields(new_schema, type_name)

            type_removed_fields = old_fields - new_fields
            type_added_fields = new_fields - old_fields

            if type_removed_fields:
                removed_fields.append((type_name, type_removed_fields))
            if type_added_fields:
                added_fields.append((type_name, type_added_fields))

            # Check for deprecated fields in old schema
            old_deprecated = self._get_deprecated_fields(old_schema, type_name)
            if old_deprecated:
                deprecated_fields.append((type_name, old_deprecated))

        if removed_fields:
            output_lines.append(f"\n❌ Removed fields in {schema_name}:")
            for type_name, fields in removed_fields:
                output_lines.append(f"  {type_name}:")
                for field in sorted(fields):
                    output_lines.append(f"    - {field}")

        if added_fields:
            output_lines.append(f"\n✅ Added fields in {schema_name}:")
            for type_name, fields in added_fields:
                output_lines.append(f"  {type_name}:")
                for field in sorted(fields):
                    output_lines.append(f"    - {field}")

        if deprecated_fields:
            output_lines.append(f"\n⚠️  Deprecated fields in {schema_name}:")
            for type_name, fields in deprecated_fields:
                output_lines.append(f"  {type_name}:")
                for field, reason in sorted(fields.items()):
                    output_lines.append(f"    - {field}: {reason}")

        # Show summary
        total_removed = sum(len(fields) for _, fields in removed_fields)
        total_added = sum(len(fields) for _, fields in added_fields)
        total_deprecated = sum(len(fields) for _, fields in deprecated_fields)
        total_removed_types = len(removed_types)
        total_added_types = len(added_types)

        output_lines.append(f"\n📈 {schema_name} Summary:")
        output_lines.append(f"  - Removed fields: {total_removed}")
        output_lines.append(f"  - Added fields: {total_added}")
        output_lines.append(f"  - Deprecated fields: {total_deprecated}")
        output_lines.append(f"  - Removed types: {total_removed_types}")
        output_lines.append(f"  - Added types: {total_added_types}")

        # Also print to console
        for line in output_lines:
            print(line)

        return output_lines


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Interactive GraphQL Validation and Schema Analysis Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python cli.py                    # Interactive mode
  python cli.py --extract          # Extract only
  python cli.py --validate         # Validate only
  python cli.py --full             # Full analysis
  python cli.py --dry-run          # Preview changes
  python cli.py --old-version 2024-04 --new-version 2025-04  # Non-interactive
        """,
    )

    # Operation modes
    parser.add_argument(
        "--extract",
        action="store_true",
        help="Extract GraphQL and Pydantic models only",
    )
    parser.add_argument("--validate", action="store_true", help="Run validation only")
    parser.add_argument(
        "--full", action="store_true", help="Run full analysis (extract + validate)"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Preview changes without applying"
    )
    parser.add_argument(
        "--interactive", action="store_true", help="Run interactive step-by-step mode"
    )
    parser.add_argument(
        "--schema-analysis", action="store_true", help="Run detailed schema analysis"
    )

    # Schema versions
    parser.add_argument(
        "--old-version", type=str, help="Old schema version (e.g., 2024-04)"
    )
    parser.add_argument(
        "--new-version",
        type=str,
        default=SHOPIFY_VERSION,
        help="New schema version (e.g., 2025-04)",
    )

    # Target and options
    parser.add_argument(
        "--path",
        type=str,
        default="..",
        help="Path to analyze (default: parent directory)",
    )
    parser.add_argument(
        "--exclude", type=str, default="", help="Comma-separated patterns to exclude"
    )
    parser.add_argument(
        "--surface-validation",
        action="store_true",
        help="Enable GraphQL and Pydantic syntax validation (no schema loading)",
    )
    parser.add_argument(
        "--schema-evolution",
        action="store_true",
        help="Enable schema evolution checks (deprecated/removed/added fields)",
    )
    parser.add_argument(
        "--no-schema-evolution",
        action="store_true",
        help="Disable schema evolution checks",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable verbose output")
    parser.add_argument(
        "--verify-schemas",
        action="store_true",
        help="Verify and display schema information after loading",
    )

    args = parser.parse_args()

    # Create CLI instance
    cli = InteractiveCLI()

    # Set options from arguments
    cli.old_version = args.old_version
    cli.new_version = args.new_version
    cli.target_path = args.path
    cli.exclude_patterns = [p.strip() for p in args.exclude.split(",") if p.strip()]
    cli.surface_validation = args.surface_validation
    cli.schema_evolution = args.schema_evolution
    if not args.schema_evolution and not args.no_schema_evolution:
        # Default behavior: if surface validation is requested, don't require schema evolution
        cli.schema_evolution = not args.surface_validation
    cli.dry_run = args.dry_run
    cli.verbose = args.verbose
    cli.verify_schemas = args.verify_schemas

    # Determine mode
    if args.interactive:
        cli.run_interactive_mode()
    elif args.extract:
        cli.target_path = cli.get_target_path() if not args.path else args.path
        results = cli.run_extraction()
        cli.display_results(results, [])
    elif args.validate:
        # --validate: only run schema evolution checks (deprecated/removed/added fields)
        schemas = None
        if cli.schema_evolution:
            if not cli.old_version or not cli.new_version:
                cli.old_version, cli.new_version = cli.get_schema_versions()
            schemas = cli.load_schemas_interactive()
        results = cli.run_extraction()
        warnings = cli.run_validation(schemas, results)
        cli.display_results(
            results, warnings, show_suggestions=True
        )  # Show suggestions for validation mode
    elif args.surface_validation:
        # --surface-validation: run surface validation (GraphQL/Pydantic syntax)
        schemas = None
        if cli.schema_evolution:
            if not cli.old_version or not cli.new_version:
                cli.old_version, cli.new_version = cli.get_schema_versions()
            schemas = cli.load_schemas_interactive()
        results = cli.run_extraction()
        warnings = cli.run_validation(schemas, results)
        cli.display_results(
            results, warnings, show_suggestions=True
        )  # Show suggestions for validation mode
    elif args.full:
        schemas = None
        if cli.schema_evolution:
            if not cli.old_version or not cli.new_version:
                cli.old_version, cli.new_version = cli.get_schema_versions()
            schemas = cli.load_schemas_interactive()
        results = cli.run_extraction()
        warnings = cli.run_validation(schemas, results)
        cli.display_results(
            results, warnings, show_suggestions=True
        )  # Show suggestions for full analysis
    elif args.dry_run:
        schemas = None
        if cli.schema_evolution:
            if not cli.old_version or not cli.new_version:
                cli.old_version, cli.new_version = cli.get_schema_versions()
            schemas = cli.load_schemas_interactive()
        results = cli.run_extraction()
        warnings = cli.run_validation(schemas, results)
        suggestions = cli.suggest_fixes(warnings)
        cli.run_dry_run(suggestions)
    elif args.verify_schemas:
        # Schema verification mode
        if not cli.old_version or not cli.new_version:
            cli.old_version, cli.new_version = cli.get_schema_versions()
        schemas = cli.load_schemas_interactive()
        cli.verify_schema_info(*schemas)
    elif args.schema_analysis:
        cli.run_schema_analysis()
    else:
        # Default to interactive mode
        cli.run_interactive_mode()


if __name__ == "__main__":
    main()

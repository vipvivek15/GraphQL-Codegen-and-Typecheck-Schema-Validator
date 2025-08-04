#!/usr/bin/env python3
"""
Reporter module for formatting and displaying extractor results.

This module handles all the printing and formatting logic for the extractor,
keeping the main extractor clean and focused on extraction logic.
"""

import json
import os
import sys
from typing import Any, Dict, List


def print_results(results: List[Dict[str, Any]]) -> None:
    """
    Print extraction results in a human-readable format.

    Args:
        results: List of extraction results from the extractor
    """
    for entry in results:
        print(f"\n=== File: {entry['file']} ===")

        if entry.get("pydantic_models"):
            print("\n-- Pydantic Models --")
            for i, model in enumerate(entry["pydantic_models"], 1):
                print(
                    f"  {i}. Model: {model.get('model_name')} (type: {model.get('type')}) lines {model.get('start_line')}-{model.get('end_line')}"
                )
                if model.get("error"):
                    print(f"     [ERROR] {model['error']}")
                else:
                    raw = model.get("raw") or ""
                    # Show first few lines of raw content for readability
                    lines = raw.splitlines()
                    if len(lines) > 15:
                        print("     Raw (first 15 lines):")
                        for line in lines[:15]:
                            print("       " + line)
                        print(f"     ... and {len(lines) - 15} more lines")
                    else:
                        print("     Raw:")
                        for line in lines:
                            print("       " + line)
                print()

        if entry.get("graphql"):
            print("\n-- GraphQL Blocks --")
            for i, block in enumerate(entry["graphql"], 1):
                print(
                    f"  {i}. Type: {block.get('type')} Name: {block.get('name')} lines {block.get('start_line')}-{block.get('end_line')}"
                )
                if block.get("type") == "fragment":
                    print(f"     Type Condition: {block.get('type_condition')}")
                if block.get("variables"):
                    print(f"     Variables: {block['variables']}")
                if block.get("error"):
                    print(f"     [ERROR] {block['error']}")
                raw = block.get("raw") or ""
                # Show first few lines of raw content for readability
                lines = raw.splitlines()
                if len(lines) > 10:
                    print("     Raw (first 10 lines):")
                    for line in lines[:10]:
                        print("       " + line)
                    print(f"     ... and {len(lines) - 10} more lines")
                else:
                    print("     Raw:")
                    for line in lines:
                        print("       " + line)
                print()


def output_json(results: List[Dict[str, Any]]) -> None:
    """
    Output extraction results as JSON for piping to other tools.

    Args:
        results: List of extraction results from the extractor
    """
    print(json.dumps(results, indent=2))


def should_print_human_readable() -> bool:
    """
    Determine if output should be human-readable or JSON.

    Returns:
        True if output should be human-readable, False for JSON
    """
    return os.isatty(1)


def report_results(results: List[Dict[str, Any]], force_print: bool = False) -> None:
    """
    Report extraction results in the appropriate format.

    Args:
        results: List of extraction results from the extractor
        force_print: If True, force human-readable output even when piped
    """
    if force_print or should_print_human_readable():
        print_results(results)
    else:
        output_json(results)


def report_errors(errors):
    """Report error messages in standard format."""
    for err in errors:
        file = err.get("file", "?")
        line = err.get("start_line", "?")
        col = err.get("start_col", "?")
        level = err.get("level", "error")
        message = err.get("message", "")
        print(f"{file}:{line}:{col}: {level}: {message}")


def report_warnings(warnings):
    """Report warning messages in standard format."""
    for warning in warnings:
        file = warning.get("file", "?")
        line = warning.get("start_line", "?")
        col = warning.get("start_col", "?")
        level = warning.get("level", "warning")
        message = warning.get("message", "")
        print(f"{file}:{line}:{col}: {level}: {message}")


def print_error(message: str) -> None:
    """Print an error message to stderr."""
    print(f"Error: {message}", file=sys.stderr)


# New validation-specific methods
class ValidationReporter:
    """Handles all output and logging for the validation tool."""

    @staticmethod
    def report_errors(errors: List[Dict[str, Any]], level: str = "error") -> None:
        """Report error messages in standard format."""
        for err in errors:
            file = err.get("file", "?")
            line = err.get("line", err.get("start_line", "?"))
            col = err.get("column", err.get("start_col", "?"))
            message = err.get("message", "")
            print(f"{file}:{line}:{col}: {level}: {message}")

    @staticmethod
    def report_warnings(warnings: List[Dict[str, Any]], level: str = "warning") -> None:
        """Report warning messages in standard format."""
        for warning in warnings:
            file = warning.get("file", "?")
            line = warning.get("line", warning.get("start_line", "?"))
            col = warning.get("column", warning.get("start_col", "?"))
            message = warning.get("message", "")
            print(f"{file}:{line}:{col}: {level}: {message}")

    @staticmethod
    def log_schema_loading(old_version: str, new_version: str) -> None:
        """Log schema loading progress."""
        print(f"Loading schemas for old version: {old_version}")
        print(f"Loading schemas for new version: {new_version}")
        print("Schemas loaded successfully")

    @staticmethod
    def log_file_processing(file_path: str) -> None:
        """Log file processing start."""
        print(f"Checking file: {file_path}")

    @staticmethod
    def log_graphql_extraction(block_count: int) -> None:
        """Log GraphQL block extraction results."""
        print(f"Extracted {block_count} GraphQL blocks")

    @staticmethod
    def log_surface_validation_extraction(block_count: int) -> None:
        """Log surface validation extraction results."""
        print(f"Surface validation: extracted {block_count} GraphQL blocks")

    @staticmethod
    def log_schema_comparison_warnings(warnings: List[Dict[str, Any]]) -> None:
        """Log schema comparison warnings."""
        print(f"Schema comparison found {len(warnings)} warnings")
        for warning in warnings:
            print(f"  Schema comparison: {warning['message']}")

    @staticmethod
    def log_graphql_block_validation(block_name: str, start_line: int) -> None:
        """Log GraphQL block validation start."""
        print(f"Validating GraphQL block: {block_name} at line {start_line}")

    @staticmethod
    def log_graphql_validation_warnings(warning_count: int) -> None:
        """Log GraphQL validation warning count."""
        print(f"Found {warning_count} GraphQL validation warnings")

    @staticmethod
    def log_surface_validation_warnings(warning_count: int) -> None:
        """Log surface validation warning count."""
        print(f"Surface validation found {warning_count} warnings")

    @staticmethod
    def log_total_warnings(warning_count: int) -> None:
        """Log total warning count."""
        print(f"Found {warning_count} warnings")

    @staticmethod
    def log_surface_validation_start(file_path: str) -> None:
        """Log surface validation start."""
        print(f"Running surface validation for {file_path}")

    # CLI-specific methods
    @staticmethod
    def print_banner() -> None:
        """Print the CLI banner."""
        print("=" * 60)
        print("🔍 GraphQL Validation & Schema Analysis Tool")
        print("=" * 60)
        print()

    @staticmethod
    def print_operation_mode_selection() -> None:
        """Print operation mode selection menu."""
        print("🎯 Select Operation Mode:")
        print("1. Verify Schemas - Load and compare schema versions")
        print("2. Analyze Schemas - Show detailed field changes (added/removed/deprecated)")
        print("3. Extract Only - Extract GraphQL and Pydantic models")
        print("4. Full Analysis - Validate + Show suggestions")
        print("5. Quit")
        print()

    @staticmethod
    def print_schema_version_selection() -> None:
        """Print schema version selection header."""
        print("\n📋 Schema Version Selection")
        print("-" * 30)

    @staticmethod
    def print_target_path_selection() -> None:
        """Print target path selection header."""
        print("\n📁 Target Path Selection")
        print("-" * 25)

    @staticmethod
    def print_validation_options() -> None:
        """Print validation options header."""
        print("\n⚙️  Validation Options")
        print("-" * 20)

    @staticmethod
    def print_extraction_start(target_path: str) -> None:
        """Print extraction start message."""
        print(f"\n🔍 Extracting GraphQL and Pydantic models from: {target_path}")

    @staticmethod
    def print_extraction_complete(
        total_files_processed: int,
        graphql_blocks_found: int,
        pydantic_models_found: int,
    ) -> None:
        """Print extraction completion message."""
        print(
            f"✅ Extraction complete! Found {total_files_processed} files with content"
        )

    @staticmethod
    def print_validation_start() -> None:
        """Print validation start message."""
        print("\n🔍 Running validation...")

    @staticmethod
    def print_validation_complete(issue_count: int) -> None:
        """Print validation completion message."""
        print(f"✅ Validation complete! Found {issue_count} issues")

    @staticmethod
    def print_schema_loading_start(old_version: str, new_version: str) -> None:
        """Print schema loading start message."""
        print("\n🔄 Loading schemas...")
        print(f"   Old version: {old_version}")
        print(f"   New version: {new_version}")

    @staticmethod
    def print_schema_loading_success() -> None:
        """Print schema loading success message."""
        print("✅ Schemas loaded successfully!")

    @staticmethod
    def print_processing_file(file_path: str) -> None:
        """Print file processing message."""
        print(f"   Processing: {file_path}")

    @staticmethod
    def print_validating_file(file_path: str) -> None:
        """Print file validation message."""
        print(f"   Validating: {file_path}")

    @staticmethod
    def print_results_header() -> None:
        """Print results header."""
        print("\n📊 Analysis Results")
        print("=" * 50)

    @staticmethod
    def print_extraction_summary(
        file_count: int, graphql_count: int, pydantic_count: int
    ) -> None:
        """Print extraction summary."""
        print(f"📁 Files analyzed: {file_count}")
        print(f"🔗 GraphQL blocks: {graphql_count}")
        print(f"📋 Pydantic models: {pydantic_count}")

    @staticmethod
    def print_validation_summary(issue_count: int) -> None:
        """Print validation summary."""
        if issue_count > 0:
            print(f"\n⚠️  Issues found: {issue_count}")
        else:
            print("\n✅ No issues found!")

    @staticmethod
    def print_category_summary(categories: Dict[str, int]) -> None:
        """Print category summary."""
        for category, count in categories.items():
            print(f"   {category.replace('_', ' ').title()}: {count}")

    @staticmethod
    def print_suggestions_header() -> None:
        """Print suggestions header."""
        print("\n🔧 Suggested Fixes")
        print("=" * 30)

    @staticmethod
    def print_dry_run_header() -> None:
        """Print dry run header."""
        print("\n🧪 Dry Run Mode - Preview Changes")
        print("=" * 40)

    @staticmethod
    def print_dry_run_summary(suggestions: List[Dict[str, Any]]) -> None:
        """Print dry run summary."""
        suggestion_count = len(suggestions)
        if suggestion_count > 0:
            print(f"📋 Would apply {suggestion_count} changes:")
            print()
        else:
            print("✅ No changes needed!")

    @staticmethod
    def print_dry_run_suggestion(index: int, suggestion: Dict[str, Any]) -> None:
        """Print individual dry run suggestion."""
        file_path = suggestion.get("file", "?")
        line = suggestion.get("line", "?")
        column = suggestion.get("column", "?")
        issue = suggestion.get("issue", "?")
        action = suggestion.get("fix", "No suggestion available")

        print(f"{index}. {file_path}:{line}:{column}")
        print(f"   Issue: {issue}")
        print(f"   Action: {action}")
        print()

    @staticmethod
    def print_dry_run_footer() -> None:
        """Print dry run footer."""
        print(
            "💡 This is a preview of suggested fixes. The tool provides suggestions but does not automatically apply changes."
        )

    @staticmethod
    def print_step_header(step_number: int, step_name: str) -> None:
        """Print step header for interactive mode."""
        print(f"\n📋 Step {step_number}: {step_name}")

    @staticmethod
    def print_analysis_complete() -> None:
        """Print analysis completion message."""
        print("\n✅ Analysis complete!")

    @staticmethod
    def print_show_details_prompt() -> None:
        """Print show details prompt."""
        print("\nShow detailed fix suggestions? (y/n) [n]: ")

    @staticmethod
    def print_suggestion_details(suggestion: Dict[str, Any]) -> None:
        """Print detailed suggestion."""
        file_path = suggestion.get("file", "?")
        line = suggestion.get("line", "?")
        column = suggestion.get("column", "?")
        issue = suggestion.get("issue", "?")
        fix = suggestion.get("fix", "No suggestion available")

        print(f"\nFile: {file_path}:{line}:{column}")
        print(f"Issue: {issue}")
        print(f"Fix: {fix}")

    @staticmethod
    def print_choice_prompt() -> None:
        """Print choice prompt."""
        print("Enter your choice (1-5): ")

    @staticmethod
    def print_invalid_choice() -> None:
        """Print invalid choice message."""
        print_error("Please enter a number between 1 and 4")

    @staticmethod
    def print_interactive_header() -> None:
        """Print interactive mode header."""
        print("🎯 Step-by-Step Guided Analysis")
        print("=" * 35)

    @staticmethod
    def print_schema_verification_header() -> None:
        """Print schema verification header."""
        print("\n🔍 Schema Verification")
        print("=" * 30)

    @staticmethod
    def print_old_schema_header(version: str) -> None:
        """Print old schema header."""
        print(f"📋 Old Schema ({version}):")

    @staticmethod
    def print_new_schema_header(version: str) -> None:
        """Print new schema header."""
        print(f"📋 New Schema ({version}):")

    @staticmethod
    def print_admin_schema_status(types_count: int, success: bool = True) -> None:
        """Print admin schema status."""
        if success:
            print(f"   Admin: {types_count} types loaded")
        else:
            print("   Admin: ❌ Failed to load")

    @staticmethod
    def print_storefront_schema_status(types_count: int, success: bool = True) -> None:
        """Print storefront schema status."""
        if success:
            print(f"   Storefront: {types_count} types loaded")
        else:
            print("   Storefront: ❌ Failed to load")

    @staticmethod
    def print_admin_comparison(old_fields: int, new_fields: int) -> None:
        """Print admin schema comparison."""
        print("\n📊 Admin Schema Comparison:")
        print(f"   Old: {old_fields} fields")
        print(f"   New: {new_fields} fields")
        print(f"   Difference: {new_fields - old_fields:+d} fields")

    @staticmethod
    def print_storefront_comparison(old_fields: int, new_fields: int) -> None:
        """Print storefront schema comparison."""
        print("\n📊 Storefront Schema Comparison:")
        print(f"   Old: {old_fields} fields")
        print(f"   New: {new_fields} fields")
        print(f"   Difference: {new_fields - old_fields:+d} fields")

    @staticmethod
    def print_schema_evolution_summary(schema_name: str, stats: Dict[str, int]) -> None:
        """Print schema evolution summary."""
        print(f"\n📈 {schema_name} Schema Evolution:")
        print(f"   ➕ Added types: {stats['added_types']}")
        print(f"   ➖ Removed types: {stats['removed_types']}")
        print(f"   ➕ Added fields: {stats['added_fields']}")
        print(f"   ➖ Removed fields: {stats['removed_fields']}")
        print(f"   ⚠️  Deprecated fields: {stats['deprecated_fields']}")

    @staticmethod
    def print_suggestions_list(suggestions: List[Dict[str, Any]]) -> None:
        """Print list of suggestions."""
        for i, suggestion in enumerate(suggestions, 1):
            file_path = suggestion.get("file", "?")
            line = suggestion.get("line", "?")
            issue = suggestion.get("issue", "?")
            fix = suggestion.get("suggestion", "?")
            print(f"   File: {file_path}:{line}")
            print(f"   Issue: {issue}")
            print(f"   Fix: {fix}")
            print()

    @staticmethod
    def print_dry_run_changes(suggestions: List[Dict[str, Any]]) -> None:
        """Print dry run changes."""
        for i, suggestion in enumerate(suggestions, 1):
            file_path = suggestion.get("file", "?")
            line = suggestion.get("line", "?")
            issue = suggestion.get("issue", "?")
            fix = suggestion.get("suggestion", "?")
            print(f"{i}. {file_path}:{line}")
            print(f"   Issue: {issue}")
            print(f"   Action: {fix}")
            print()

    @staticmethod
    def print_schema_evolution_analysis_header() -> None:
        """Print schema evolution analysis header."""
        print("\n🔍 Schema Evolution Analysis:")
        print("=" * 40)

    @staticmethod
    def print_no_files_found() -> None:
        """Print no files found message."""
        print("No files with GraphQL or Pydantic content found.")

    @staticmethod
    def print_no_issues_found() -> None:
        """Print no issues found message."""
        print("✅ No issues found!")

    @staticmethod
    def print_extraction_summary_detailed(
        total_files: int,
        total_pydantic: int,
        query_count: int,
        mutation_count: int,
        subscription_count: int,
        fragment_count: int,
        total_graphql: int,
    ) -> None:
        """Print detailed extraction summary."""
        print("\n📊 Extraction Summary:")
        print(f"   📁 Files analyzed: {total_files}")
        print(f"   📋 Pydantic models: {total_pydantic}")
        print(f"   🔗 GraphQL queries: {query_count}")
        print(f"   🔄 GraphQL mutations: {mutation_count}")
        print(f"   📡 GraphQL subscriptions: {subscription_count}")
        print(f"   🧩 GraphQL fragments: {fragment_count}")
        print(f"   📊 Total GraphQL blocks: {total_graphql}")

    @staticmethod
    def print_issues_by_category(
        category: str, issues: List[Dict[str, Any]], verbose: bool = False
    ) -> None:
        """Print issues by category."""
        if verbose:
            print(f"\n📋 {category} Issues ({len(issues)}):")
            for issue in issues:
                file_path = issue.get("file", "?")
                line = issue.get("line", issue.get("start_line", "?"))
                column = issue.get("column", issue.get("start_col", "?"))
                message = issue.get("message", "?")
                print(f"   {file_path}:{line}:{column} - {message}")
        else:
            print(f"   {len(issues)} issues found (use --verbose to see details)")

    @staticmethod
    def print_suggestions_summary(
        suggestions: List[Dict[str, Any]], verbose: bool = False
    ) -> None:
        """Print suggestions summary."""
        if verbose:
            print(f"\n🔧 Suggested Fixes ({len(suggestions)}):")
            for i, suggestion in enumerate(suggestions, 1):
                file_path = suggestion.get("file", "?")
                line = suggestion.get("line", "?")
                issue = suggestion.get("issue", "?")
                fix = suggestion.get("suggestion", "?")
                print(f"{i}. {file_path}:{line}")
                print(f"   Issue: {issue}")
                print(f"   Fix: {fix}")
                print()
        else:
            print(f"\n🔧 Suggested Fixes ({len(suggestions)}):")
            print("   Use --verbose to see detailed fix suggestions")

    @staticmethod
    def print_goodbye() -> None:
        """Print goodbye message."""
        print("👋 Goodbye!")

    @staticmethod
    def print_menu_return_prompt() -> None:
        """Print menu return prompt."""
        print("\n" + "=" * 50)
        print("Would you like to return to the main menu? (y/n): ", end="")

    @staticmethod
    def print_skipping_schema_evolution() -> None:
        """Print skipping schema evolution message."""
        print("⏭️  Skipping schema versions and loading (schema evolution disabled)")

    @staticmethod
    def print_skipping_suggestions() -> None:
        """Print skipping suggestions message."""
        print("\nSkipping detailed suggestions.")

    @staticmethod
    def print_empty_line() -> None:
        """Print an empty line."""
        print()

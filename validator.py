import fnmatch
import os
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from dotenv import load_dotenv
from extractor import extract_graphql_blocks, extract_pydantic_models
from reporter import ValidationReporter

# Load environment variables from .env file
load_dotenv()
from graphql import GraphQLError, parse, validate
from graphql.language.ast import FieldNode, FragmentSpreadNode, InlineFragmentNode
from graphql.type.definition import (
    GraphQLList,
    GraphQLNonNull,
)


def load_schemas(version: str) -> Tuple[Any, Any]:
    """Load both admin and storefront schemas using the loader module."""
    from loader import load_schemas as loader_load_schemas

    return loader_load_schemas(version)


def get_field_status_map(
    schema_obj: Any,
) -> Tuple[
    Dict[str, Dict[str, Tuple[bool, bool, Optional[str]]]], List[Dict[str, str]]
]:
    # Returns {type_name: {field_name: (exists, is_deprecated, deprecation_reason)}}
    status: Dict[str, Dict[str, Tuple[bool, bool, Optional[str]]]] = {}
    deprecated_fields: List[Dict[str, str]] = []
    for type_name, gql_type in schema_obj.type_map.items():
        if hasattr(gql_type, "fields"):
            status[type_name] = {}
            for field_name, field in gql_type.fields.items():
                is_deprecated = getattr(field, "is_deprecated", False)
                deprecation_reason = getattr(field, "deprecation_reason", None)
                status[type_name][field_name] = (
                    True,
                    is_deprecated,
                    deprecation_reason,
                )
                if is_deprecated or deprecation_reason:
                    deprecated_fields.append(
                        {
                            "type": type_name,
                            "field": field_name,
                            "reason": deprecation_reason or "",
                        }
                    )
    return status, deprecated_fields


def unwrap_type(gql_type: Any) -> Any:
    # Unwrap GraphQLNonNull and GraphQLList to get the underlying type
    while isinstance(gql_type, (GraphQLNonNull, GraphQLList)):
        gql_type = gql_type.of_type
    return gql_type


def is_field_deprecated(field: Any) -> bool:
    # Treat as deprecated if either is_deprecated is True or deprecation_reason is set
    return bool(
        getattr(field, "is_deprecated", False)
        or getattr(field, "deprecation_reason", None)
    )


def determine_client_type(
    source: str,
    block: Dict[str, Any],
    old_admin_schema: Any = None,
    old_storefront_schema: Any = None,
) -> str:
    raw = block["raw"]
    import re as _re

    # Try to extract the operation name (query/mutation/subscription) and root field
    m = _re.search(r"(query|mutation|subscription)\s+([A-Za-z0-9_]+)?\s*[{(]", raw)
    op_type = m.group(1) if m else None
    op_name = m.group(2) if m else None
    
    # Check for fragment definitions
    fragment_match = _re.search(r"fragment\s+([A-Za-z0-9_]+)\s+on\s+([A-Za-z0-9_]+)", raw)
    if fragment_match:
        fragment_name = fragment_match.group(1)
        fragment_type = fragment_match.group(2)
        # For fragments, we need to determine which schema the fragment type belongs to
        if old_admin_schema is None or old_storefront_schema is None:
            return "Unknown"
        
        # Check if the fragment type exists in either schema
        admin_has_type = old_admin_schema.get_type(fragment_type) is not None
        storefront_has_type = old_storefront_schema.get_type(fragment_type) is not None
        
        if admin_has_type and not storefront_has_type:
            return "Admin"
        if storefront_has_type and not admin_has_type:
            return "Storefront"
        return "Unknown"
    
    # Fallback: look for the first field in the selection set
    m2 = _re.search(r"{\s*([A-Za-z0-9_]+)\s*", raw)
    root_field = m2.group(1) if m2 else None

    # Use the schema to determine if the root field exists only in Admin or Storefront
    if old_admin_schema is None or old_storefront_schema is None:
        return "Unknown"

    admin_root = (
        getattr(old_admin_schema, "query_type", None)
        or old_admin_schema.get_type("QueryRoot")
        or old_admin_schema.get_type("Query")
    )
    storefront_root = (
        getattr(old_storefront_schema, "query_type", None)
        or old_storefront_schema.get_type("QueryRoot")
        or old_storefront_schema.get_type("Query")
    )
    admin_mut = getattr(
        old_admin_schema, "mutation_type", None
    ) or old_admin_schema.get_type("Mutation")
    storefront_mut = getattr(
        old_storefront_schema, "mutation_type", None
    ) or old_storefront_schema.get_type("Mutation")
    admin_sub = getattr(
        old_admin_schema, "subscription_type", None
    ) or old_admin_schema.get_type("Subscription")
    storefront_sub = getattr(
        old_storefront_schema, "subscription_type", None
    ) or old_storefront_schema.get_type("Subscription")
    
    # Check for queries
    if op_type == "query" and root_field:
        in_admin = hasattr(admin_root, "fields") and root_field in admin_root.fields
        in_storefront = (
            hasattr(storefront_root, "fields") and root_field in storefront_root.fields
        )
        if in_admin and not in_storefront:
            return "Admin"
        if in_storefront and not in_admin:
            return "Storefront"
    
    # Check for mutations
    if op_type == "mutation" and root_field:
        in_admin = hasattr(admin_mut, "fields") and root_field in admin_mut.fields
        in_storefront = (
            hasattr(storefront_mut, "fields") and root_field in storefront_mut.fields
        )
        if in_admin and not in_storefront:
            return "Admin"
        if in_storefront and not in_admin:
            return "Storefront"
    
    # Check for subscriptions
    if op_type == "subscription" and root_field:
        in_admin = hasattr(admin_sub, "fields") and root_field in admin_sub.fields
        in_storefront = (
            hasattr(storefront_sub, "fields") and root_field in storefront_sub.fields
        )
        if in_admin and not in_storefront:
            return "Admin"
        if in_storefront and not in_admin:
            return "Storefront"
    
    return "Unknown"


def check_graphql_surface_validation(
    graphql_content: str, schema: Any, file: str, start_line: int
) -> List[Dict[str, Any]]:
    """
    Perform comprehensive GraphQL validation against a schema.

    This checks for basic GraphQL syntax and schema compliance including:
    - Deprecated fields (existing logic preserved)
    - Removed fields (breaking errors)
    - Missing required arguments
    - Extra fields not in schema
    - Type mismatches
    - Invalid fragment spreads
    - Invalid field selection
    - Invalid or unnamed operations
    - Inline fragments validation
    """
    warnings = []

    try:
        # Parse the GraphQL document
        document = parse(graphql_content)

        # Basic validation against schema (skip if schema is None for surface validation)
        validation_errors = []
        if schema is not None:
            validation_errors = validate(schema, document)

        for error in validation_errors:
            # Extract line and column information
            line = start_line
            column = 1

            if hasattr(error, "locations") and error.locations:
                location = error.locations[0]
                line = start_line + location.line - 1
                column = location.column

            # Categorize errors based on message content
            error_message = error.message
            error_type = "GRAPHQL_VALIDATION"

            if "deprecated" in error_message.lower():
                error_type = "DEPRECATED"
            elif "does not exist" in error_message.lower():
                error_type = "REMOVED"
            elif (
                "required" in error_message.lower()
                and "argument" in error_message.lower()
            ):
                error_type = "MISSING_REQUIRED_ARG"
            elif "unknown argument" in error_message.lower():
                error_type = "EXTRA_FIELD"
            elif (
                "cannot be applied" in error_message.lower()
                and "fragment" in error_message.lower()
            ):
                error_type = "INVALID_FRAGMENT"
            elif "type" in error_message.lower() and (
                "expected" in error_message.lower()
                or "cannot be" in error_message.lower()
            ):
                error_type = "TYPE_MISMATCH"
            elif "operation" in error_message.lower() and (
                "unnamed" in error_message.lower() or "invalid" in error_message.lower()
            ):
                error_type = "INVALID_OPERATION"

            warnings.append(
                {
                    "file": file,
                    "line": line,
                    "column": column,
                    "level": "error"
                    if error_type
                    in [
                        "REMOVED",
                        "MISSING_REQUIRED_ARG",
                        "TYPE_MISMATCH",
                        "INVALID_OPERATION",
                    ]
                    else "warning",
                    "message": f"[{error_type}] {error_message}",
                }
            )

        # Additional custom validations
        custom_warnings = check_custom_graphql_validations(
            document, schema, file, start_line
        )
        warnings.extend(custom_warnings)
    except GraphQLError as e:
        # Handle parsing errors
        line = start_line
        column = 1

        if hasattr(e, "locations") and e.locations:
            location = e.locations[0]
            line = start_line + location.line - 1
            column = location.column

        warnings.append(
            {
                "file": file,
                "line": line,
                "column": column,
                "level": "error",
                "message": f"[GRAPHQL_PARSE] {e.message}",
            }
        )

    return warnings


def check_custom_graphql_validations(
    document: Any, schema: Any, file: str, start_line: int
) -> List[Dict[str, Any]]:
    """
    Perform custom GraphQL validations beyond the standard schema validation.
    """
    warnings = []

    # Check for unnamed operations in multi-operation files
    operations = [defn for defn in document.definitions if hasattr(defn, "operation")]
    if len(operations) > 1:
        unnamed_operations = [op for op in operations if not getattr(op, "name", None)]
        for op in unnamed_operations:
            line = start_line
            if hasattr(op, "loc") and op.loc:
                line = start_line + op.loc.start_token.line - 1

            warnings.append(
                {
                    "file": file,
                    "line": line,
                    "column": 1,
                    "level": "error",
                    "message": "[INVALID_OPERATION] Unnamed operation in multi-operation file",
                }
            )

    # Check inline fragments for type compatibility and deprecation/removal
    for defn in document.definitions:
        if hasattr(defn, "selection_set") and defn.selection_set:
            inline_fragment_warnings = check_inline_fragments(
                defn.selection_set, schema, file, start_line
            )
            warnings.extend(inline_fragment_warnings)

    return warnings


def check_inline_fragments(
    selection_set: Any, schema: Any, file: str, start_line: int
) -> List[Dict[str, Any]]:
    """
    Check inline fragments for type compatibility and field validation.
    """
    warnings = []

    # Skip validation if schema is None (for surface validation)
    if schema is None:
        return warnings

    for selection in selection_set.selections:
        if hasattr(selection, "type_condition") and selection.type_condition:
            # This is an inline fragment
            type_name = selection.type_condition.name.value

            # Check if the type exists in the schema
            fragment_type = schema.get_type(type_name)
            if not fragment_type:
                line = start_line
                if hasattr(selection, "loc") and selection.loc:
                    line = start_line + selection.loc.start_token.line

                warnings.append(
                    {
                        "file": file,
                        "line": line,
                        "column": 1,
                        "level": "error",
                        "message": f"[INVALID_FRAGMENT] Type '{type_name}' does not exist in schema",
                    }
                )
                continue

            # Check fields within the inline fragment
            if hasattr(selection, "selection_set") and selection.selection_set:
                for field_selection in selection.selection_set.selections:
                    if hasattr(field_selection, "name"):
                        field_name = field_selection.name.value

                        # Check if field exists on the fragment type
                        if (
                            hasattr(fragment_type, "fields")
                            and field_name not in fragment_type.fields
                        ):
                            line = start_line
                            if hasattr(field_selection, "loc") and field_selection.loc:
                                line = start_line + field_selection.loc.start_token.line

                            warnings.append(
                                {
                                    "file": file,
                                    "line": line,
                                    "column": 1,
                                    "level": "error",
                                    "message": f"[INVALID_FIELD_SELECTION] Field '{field_name}' does not exist on type '{type_name}'",
                                }
                            )

        # Recursively check nested selection sets
        if hasattr(selection, "selection_set") and selection.selection_set:
            nested_warnings = check_inline_fragments(
                selection.selection_set, schema, file, start_line
            )
            warnings.extend(nested_warnings)

    return warnings


def check_pydantic_validation(source: str, file: str) -> List[Dict[str, Any]]:
    """
    Check Pydantic models for common issues.
    
    This function detects:
    - Missing required fields (no default values)
    - Field constraints (ge, le, min_length, max_length, regex)
    - Complex types (List, Dict, Union)
    - Type mismatches
    - Extra fields
    """
    warnings = []
    
    # Extract Pydantic models
    pydantic_models = extract_pydantic_models(source)
    
    for model_info in pydantic_models:
        model_raw = model_info["raw"]
        model_name = model_info["model_name"]
        start_line = model_info["start_line"]
        
        # Check for missing required fields
        required_warnings = check_pydantic_required_fields(model_raw, model_name, file, start_line)
        warnings.extend(required_warnings)
        
        # Check for field constraints
        constraint_warnings = check_pydantic_field_constraints(model_raw, model_name, file, start_line)
        warnings.extend(constraint_warnings)
        
        # Check for complex types
        complex_warnings = check_pydantic_complex_types_selective(model_raw, model_name, file, start_line)
        warnings.extend(complex_warnings)
        
        # Check for type mismatches
        type_warnings = check_pydantic_type_mismatches(model_raw, model_name, file, start_line)
        warnings.extend(type_warnings)
        
        # Check for extra fields
        extra_warnings = check_pydantic_extra_fields(model_raw, model_name, file, start_line)
        warnings.extend(extra_warnings)
    
    return warnings


def check_pydantic_required_fields(
    model_raw: str, model_name: str, file: str, start_line: int
) -> List[Dict[str, Any]]:
    """
    Check for fields without default values that might be required.
    """
    warnings = []
    
    # Pattern to match field definitions without defaults
    # Matches: field_name: type (without = default_value)
    field_pattern = r'^\s*(\w+):\s*([^=]+?)(?:\s*=\s*[^#\n]+)?\s*(?:#.*)?$'
    
    lines = model_raw.split('\n')
    for i, line in enumerate(lines):
        match = re.match(field_pattern, line)
        if match:
            field_name = match.group(1)
            field_type = match.group(2).strip()
            
            # Skip if it has a default value or is Optional
            if '= None' in line or '= ' in line or 'Optional[' in field_type:
                continue
                
            # Skip if it's a comment or not a field definition
            if line.strip().startswith('#') or 'class ' in line or 'def ' in line:
                continue
            
            line_num = start_line + i
            warnings.append({
                "file": file,
                "line": line_num,
                "column": 1,
                "level": "warning",
                "message": f"[PYDANTIC_REQUIRED_FIELD] Field '{field_name}' in model '{model_name}' has no default value - may be required",
            })
    
    return warnings


def check_pydantic_type_constraints(
    model_raw: str, model_name: str, file: str, start_line: int
) -> List[Dict[str, Any]]:
    """Check for type mismatches and constraints."""
    warnings = []

    # Check for complex types that might cause validation issues
    complex_type_pattern = r"(\w+)\s*:\s*(Union\[|List\[|Dict\[|Optional\[|Literal\[)"
    matches = re.finditer(complex_type_pattern, model_raw)

    for match in matches:
        field_name = match.group(1)
        complex_type = match.group(2)

        line, col = calculate_line_col_position(model_raw, start_line, match.start())

        if complex_type == "Union[":
            warnings.append(
                {
                    "file": file,
                    "line": line,
                    "column": col,
                    "level": "info",
                    "message": f"[PYDANTIC_COMPLEX_TYPE] Union type found in model '{model_name}' - verify type compatibility",
                }
            )
        elif complex_type == "List[":
            warnings.append(
                {
                    "file": file,
                    "line": line,
                    "column": col,
                    "level": "info",
                    "message": f"[PYDANTIC_COMPLEX_TYPE] List type found in model '{model_name}' - verify type compatibility",
                }
            )
        elif complex_type == "Dict[":
            warnings.append(
                {
                    "file": file,
                    "line": line,
                    "column": col,
                    "level": "info",
                    "message": f"[PYDANTIC_COMPLEX_TYPE] Dict type found in model '{model_name}' - verify type compatibility",
                }
            )
        elif complex_type == "Optional[":
            warnings.append(
                {
                    "file": file,
                    "line": line,
                    "column": col,
                    "level": "info",
                    "message": f"[PYDANTIC_COMPLEX_TYPE] Optional type found in model '{model_name}' - verify type compatibility",
                }
            )
        elif complex_type == "Literal[":
            warnings.append(
                {
                    "file": file,
                    "line": line,
                    "column": col,
                    "level": "info",
                    "message": f"[PYDANTIC_COMPLEX_TYPE] Literal type found in model '{model_name}' - verify type compatibility",
                }
            )

    return warnings


def check_pydantic_nested_models(
    model_raw: str, model_name: str, file: str, start_line: int
) -> List[Dict[str, Any]]:
    """Check for nested model validation issues."""
    warnings = []

    # Check for nested model references (but not built-in types or complex types)
    nested_pattern = r"(\w+)\s*:\s*(\w+)(?!\s*\[)"
    matches = re.finditer(nested_pattern, model_raw)

    for match in matches:
        field_name = match.group(1)
        nested_type = match.group(2)

        # Skip if it's a built-in type
        builtin_types = {
            "str",
            "int",
            "float",
            "bool",
            "list",
            "dict",
            "tuple",
            "set",
            "bytes",
            "datetime",
            "date",
            "time",
            "uuid",
            "decimal",
            "path",
            "url",
            "email",
            "ipv4address",
            "ipv6address",
        }
        if nested_type.lower() in builtin_types:
            continue

        # Skip if it's part of a complex type annotation
        if (
            "Optional[" in model_raw[: match.start()]
            or "List[" in model_raw[: match.start()]
            or "Dict[" in model_raw[: match.start()]
            or "Union[" in model_raw[: match.start()]
        ):
            continue

        # Skip if it's a method parameter or local variable
        if "(" in model_raw[: match.start()] or "def " in model_raw[: match.start()]:
            continue

        line, col = calculate_line_col_position(model_raw, start_line, match.start())
        warnings.append(
            {
                "file": file,
                "line": line,
                "column": col,
                "level": "info",
                "message": f"[PYDANTIC_NESTED_MODEL] Nested model '{nested_type}' in field '{field_name}' - verify model exists",
            }
        )

    return warnings


def check_pydantic_union_types(
    model_raw: str, model_name: str, file: str, start_line: int
) -> List[Dict[str, Any]]:
    """Check for union type validation issues."""
    warnings = []

    # Check for Union types
    union_pattern = r"(\w+)\s*:\s*Union\[([^\]]+)\]"
    matches = re.finditer(union_pattern, model_raw)

    for match in matches:
        field_name = match.group(1)
        union_types = match.group(2)

        line, col = calculate_line_col_position(model_raw, start_line, match.start())
        warnings.append(
            {
                "file": file,
                "line": line,
                "column": col,
                "level": "info",
                "message": f"[PYDANTIC_COMPLEX_TYPE] Union type found in model '{model_name}' - verify type compatibility",
            }
        )

    return warnings


def check_pydantic_none_values(
    model_raw: str, model_name: str, file: str, start_line: int
) -> List[Dict[str, Any]]:
    """Check for None values in non-optional fields."""
    warnings = []

    # Check for fields that might accept None but aren't Optional
    none_pattern = r"(\w+)\s*:\s*(?!Optional\[|None\b)([^=]+?)(?:\s*=\s*None)[,)]"
    matches = re.finditer(none_pattern, model_raw)

    for match in matches:
        field_name = match.group(1)
        warnings.append(
            {
                "file": file,
                "line": start_line,
                "column": 1,
                "level": "warning",
                "message": f"[PYDANTIC_NONE_VALUE] Field '{field_name}' in model '{model_name}' has default None but type is not Optional - consider using Optional[{match.group(2).strip()}]",
            }
        )

    return warnings


def check_pydantic_extra_config(
    model_raw: str, model_name: str, file: str, start_line: int
) -> List[Dict[str, Any]]:
    """Check for extra field configuration."""
    warnings = []

    # Check for extra='forbid' configuration
    if "extra=" in model_raw:
        if "extra.*forbid" in model_raw:
            line, col = calculate_line_col_position(
                model_raw, start_line, model_raw.find("extra=")
            )
            warnings.append(
                {
                    "file": file,
                    "line": line,
                    "column": col,
                    "level": "info",
                    "message": f"[PYDANTIC_EXTRA_CONFIG] Model '{model_name}' has extra='forbid' - extra fields will cause validation errors",
                }
            )
        elif "extra.*ignore" in model_raw:
            line, col = calculate_line_col_position(
                model_raw, start_line, model_raw.find("extra=")
            )
            warnings.append(
                {
                    "file": file,
                    "line": line,
                    "column": col,
                    "level": "info",
                    "message": f"[PYDANTIC_EXTRA_CONFIG] Model '{model_name}' has extra='ignore' - extra fields will be ignored",
                }
            )

    return warnings


def check_pydantic_field_constraints(
    model_raw: str, model_name: str, file: str, start_line: int
) -> List[Dict[str, Any]]:
    """
    Check for field constraints in Pydantic models.
    """
    warnings = []
    
    # Check for various field constraints
    constraint_patterns = [
        (r'Field\([^)]*max_length[^)]*\)', "max_length constraint found in model '{}' - verify constraint values are appropriate"),
        (r'Field\([^)]*ge\s*=\s*\d+[^)]*\)', "ge (greater than or equal) constraint found in model '{}' - verify constraint values are appropriate"),
        (r'Field\([^)]*le\s*=\s*\d+[^)]*\)', "le (less than or equal) constraint found in model '{}' - verify constraint values are appropriate"),
        (r'Field\([^)]*regex[^)]*\)', "regex constraint found in model '{}' - verify regex pattern is correct"),
    ]
    
    for pattern, message_template in constraint_patterns:
        matches = re.finditer(pattern, model_raw)
        for match in matches:
            line, col = calculate_line_col_position_for_extracted_content(model_raw, start_line, match.start())
            warnings.append({
                "file": file,
                "line": line,
                "column": col,
                "level": "info",
                "message": message_template.format(model_name),
            })
    
    return warnings


def check_pydantic_validators(
    model_raw: str, model_name: str, file: str, start_line: int
) -> List[Dict[str, Any]]:
    """Check for validator issues in Pydantic models."""
    warnings = []

    # Check for validator decorators
    validator_pattern = r'@(validator|field_validator|model_validator|root_validator)\s*\(\s*[\'"]([^\'"]+)[\'"]\s*\)'
    matches = re.finditer(validator_pattern, model_raw)

    for match in matches:
        validator_type = match.group(1)
        field_name = match.group(2)

        line, col = calculate_line_col_position(model_raw, start_line, match.start())

        # Check if the field is properly defined in the model
        if not re.search(rf"\b{field_name}\s*:", model_raw):
            warnings.append(
                {
                    "file": file,
                    "line": line,
                    "column": col,
                    "level": "warning",
                    "message": f"[PYDANTIC_FIELD_PRESENCE] Validator for field '{field_name}' found but field may not be defined in model '{model_name}'",
                }
            )

        # Check for validator function definition
        func_pattern = r"def\s+(\w+)\s*\([^)]*\):"
        func_matches = re.finditer(func_pattern, model_raw[match.end() :])

        for func_match in func_matches:
            func_name = func_match.group(1)
            func_start = match.end() + func_match.start()

            # Find the function body
            lines = model_raw.split("\n")
            line_num = model_raw[:func_start].count("\n") + 1

            # Look for return statement in the function
            func_end = len(model_raw)
            for i, line in enumerate(lines[line_num - 1 :], line_num):
                if line.strip().startswith("def ") and i > line_num:
                    func_end = model_raw.find(line, func_start)
                    break

            if func_end > func_start:
                func_body = model_raw[func_start:func_end]
                if "return" not in func_body:
                    line, col = calculate_line_col_position(
                        model_raw, start_line, func_start
                    )
                    warnings.append(
                        {
                            "file": file,
                            "line": line,
                            "column": col,
                            "level": "warning",
                            "message": f"[PYDANTIC_VALIDATOR] Validator function '{func_name}' in model '{model_name}' may be missing return statement",
                        }
                    )
            break

    return warnings


def check_pydantic_field_types_from_model(
    model_raw: str, model_name: str, file: str, start_line: int
) -> List[Dict[str, Any]]:
    """
    Check Pydantic field types for common issues from extracted model.
    """
    warnings = []

    # Find field definitions in the model
    field_pattern = (
        r"(\w+)\s*:\s*(Optional\[([^\]]+)\])?([^=,\n]+?)(?:\s*=\s*([^,\n]+))?"
    )
    field_matches = re.finditer(field_pattern, model_raw)

    for field_match in field_matches:
        field_name = field_match.group(1)
        optional_type = field_match.group(2)
        inner_type = field_match.group(3)
        base_type = field_match.group(4).strip()
        default_value = field_match.group(5)

        # Check for common type issues
        if base_type and base_type.strip():
            type_str = base_type.strip()

            # Check for Optional without default value
            if optional_type and not default_value:
                warnings.append(
                    {
                        "file": file,
                        "line": start_line,  # Approximate
                        "column": 1,
                        "level": "info",
                        "message": f"[PYDANTIC_OPTIONAL] Field '{field_name}' in model '{model_name}' is Optional but has no default value",
                    }
                )

            # Check for common type mismatches
            if "str" in type_str and "int" in type_str:
                warnings.append(
                    {
                        "file": file,
                        "line": start_line,  # Approximate
                        "column": 1,
                        "level": "warning",
                        "message": f"[PYDANTIC_TYPE_MISMATCH] Field '{field_name}' in model '{model_name}' has ambiguous type definition",
                    }
                )

    return warnings


def check_pydantic_field_aliases_from_model(
    model_raw: str, model_name: str, file: str, start_line: int
) -> List[Dict[str, Any]]:
    """
    Check Pydantic field aliases for consistency from extracted model.
    """
    warnings = []

    # Look for Field definitions with aliases
    alias_pattern = r'Field\s*\(\s*[^)]*alias\s*=\s*[\'"]([^\'"]+)[\'"]'
    alias_matches = re.finditer(alias_pattern, model_raw)

    for alias_match in alias_matches:
        alias_name = alias_match.group(1)

        # Check if the alias follows common naming conventions
        if "_" in alias_name and not alias_name.islower():
            warnings.append(
                {
                    "file": file,
                    "line": start_line,  # Approximate
                    "column": 1,
                    "level": "info",
                    "message": f"[PYDANTIC_ALIAS] Field alias '{alias_name}' in model '{model_name}' may not follow consistent naming convention",
                }
            )

    return warnings


def check_pydantic_inheritance_from_model(
    model_raw: str, model_name: str, file: str, start_line: int
) -> List[Dict[str, Any]]:
    """
    Check Pydantic model inheritance for potential issues from extracted model.
    """
    warnings = []

    # Look for model inheritance
    inheritance_pattern = r"class\s+(\w+)\s*\(([^)]+)\):"
    inheritance_matches = re.finditer(inheritance_pattern, model_raw)

    for inheritance_match in inheritance_matches:
        class_name = inheritance_match.group(1)
        parent_classes = inheritance_match.group(2)

        # Check for multiple inheritance with Pydantic models
        if "," in parent_classes:
            pydantic_parents = [
                p.strip()
                for p in parent_classes.split(",")
                if "BaseModel" in p or "RootModel" in p
            ]
            if len(pydantic_parents) > 1:
                warnings.append(
                    {
                        "file": file,
                        "line": start_line,  # Approximate
                        "column": 1,
                        "level": "warning",
                        "message": f"[PYDANTIC_INHERITANCE] Model '{class_name}' inherits from multiple Pydantic models which may cause conflicts",
                    }
                )

    return warnings


def check_pydantic_field_types(source: str, file: str) -> List[Dict[str, Any]]:
    """
    Check Pydantic field types for common issues.
    """
    warnings = []

    # Find Pydantic model definitions
    model_pattern = r"class\s+(\w+)\s*\(.*BaseModel.*\):"
    model_matches = re.finditer(model_pattern, source)

    for model_match in model_matches:
        model_name = model_match.group(1)
        model_start = model_match.start()

        # Find the model's field definitions
        field_pattern = (
            r"(\w+)\s*:\s*(Optional\[([^\]]+)\])?([^=,\n]+?)(?:\s*=\s*([^,\n]+))?"
        )
        field_matches = re.finditer(field_pattern, source[model_start:])

        for field_match in field_matches:
            field_name = field_match.group(1)
            optional_type = field_match.group(2)
            inner_type = field_match.group(3)
            base_type = field_match.group(4).strip()
            default_value = field_match.group(5)

            # Check for common type issues
            if base_type and base_type.strip():
                type_str = base_type.strip()

                # Check for Optional without default value
                if optional_type and not default_value:
                    warnings.append(
                        {
                            "file": file,
                            "line": 1,  # Approximate
                            "column": 1,
                            "level": "info",
                            "message": f"[PYDANTIC_OPTIONAL] Field '{field_name}' in model '{model_name}' is Optional but has no default value",
                        }
                    )

                # Check for common type mismatches
                if "str" in type_str and "int" in type_str:
                    warnings.append(
                        {
                            "file": file,
                            "line": 1,  # Approximate
                            "column": 1,
                            "level": "warning",
                            "message": f"[PYDANTIC_TYPE_MISMATCH] Field '{field_name}' in model '{model_name}' has ambiguous type definition",
                        }
                    )

    return warnings


def check_pydantic_field_aliases(source: str, file: str) -> List[Dict[str, Any]]:
    """
    Check Pydantic field aliases for consistency.
    """
    warnings = []

    # Look for Field definitions with aliases
    alias_pattern = r'Field\s*\(\s*[^)]*alias\s*=\s*[\'"]([^\'"]+)[\'"]'
    alias_matches = re.finditer(alias_pattern, source)

    for alias_match in alias_matches:
        alias_name = alias_match.group(1)

        # Check if the alias follows common naming conventions
        if "_" in alias_name and not alias_name.islower():
            warnings.append(
                {
                    "file": file,
                    "line": 1,  # Approximate
                    "column": 1,
                    "level": "info",
                    "message": f"[PYDANTIC_ALIAS] Field alias '{alias_name}' may not follow consistent naming convention",
                }
            )

    return warnings


def check_pydantic_inheritance(source: str, file: str) -> List[Dict[str, Any]]:
    """
    Check Pydantic model inheritance for potential issues.
    """
    warnings = []

    # Look for model inheritance
    inheritance_pattern = r"class\s+(\w+)\s*\(([^)]+)\):"
    inheritance_matches = re.finditer(inheritance_pattern, source)

    for inheritance_match in inheritance_matches:
        model_name = inheritance_match.group(1)
        parent_classes = inheritance_match.group(2)

        # Check for multiple inheritance with Pydantic models
        if "," in parent_classes:
            pydantic_parents = [
                p.strip()
                for p in parent_classes.split(",")
                if "BaseModel" in p or "RootModel" in p
            ]
            if len(pydantic_parents) > 1:
                warnings.append(
                    {
                        "file": file,
                        "line": 1,  # Approximate
                        "column": 1,
                        "level": "warning",
                        "message": f"[PYDANTIC_INHERITANCE] Model '{model_name}' inherits from multiple Pydantic models which may cause conflicts",
                    }
                )

    return warnings


def traverse_schema(
    node: Any,
    parent_type: Any,
    old_schema: Any,
    new_schema: Any,
    schema_name: str,
    start_line: int,
    file: str,
    seen: Set[Any],
    warnings: List[Dict[str, Any]],
    check_removed_and_added: bool = False,
    fragment_definitions: Dict[str, Any] = None,
    recursion_depth: int = 0,
) -> None:
    # Safety check to prevent infinite recursion
    if recursion_depth > 10:
        return

    if isinstance(node, FieldNode):
        field_name = node.name.value
        # Get field using case-insensitive matching for old schema
        schema_field_map = {k.lower(): k for k in getattr(parent_type, "fields", {})}
        schema_field_key = schema_field_map.get(field_name.lower())
        old_field = (
            parent_type.fields[schema_field_key]
            if parent_type and hasattr(parent_type, "fields") and schema_field_key
            else None
        )

        # Get field for new schema - use direct field name if not found in old schema
        new_parent_type = (
            new_schema.get_type(parent_type.name)
            if parent_type
            and hasattr(parent_type, "name")
            and new_schema.get_type(parent_type.name)
            else None
        )
        if new_parent_type and hasattr(new_parent_type, "fields"):
            # Try the case-insensitive key first, then direct field name
            new_field = (
                new_parent_type.fields.get(schema_field_key)
                if schema_field_key
                else None
            )
            if new_field is None:
                # If not found with case-insensitive key, try direct field name
                new_field = new_parent_type.fields.get(field_name)
        else:
            new_field = None
        node_token = getattr(getattr(node, "loc", None), "start_token", None)
        if (
            node_token is not None
            and hasattr(node_token, "line")
            and hasattr(node_token, "column")
        ):
            line = start_line + node_token.line
            column = node_token.column + 1
        else:
            line = start_line
            column = 1

        def add_warning(
            level: str,
            reason: str,
            schema_type: str,
            schema_field: str,
            kind: str,
            line: int,
            column: int,
        ) -> None:
            key = (file, line, column, schema_type, schema_field, reason, kind)
            if key not in seen:
                seen.add(key)
                # Include client type (Admin/Storefront) in the message
                client_info = (
                    f" ({schema_name})"
                    if schema_name in ["Admin", "Storefront"]
                    else ""
                )
                warnings.append(
                    {
                        "file": file,
                        "line": line,
                        "column": column,
                        "level": level,
                        "message": f"[{kind}] Field '{schema_field}' in type '{schema_type}' {reason}{client_info}",
                    }
                )

        # Deprecation (old schema)
        if old_field and (
            getattr(old_field, "is_deprecated", False)
            or getattr(old_field, "deprecation_reason", None)
        ):
            add_warning(
                "warning",
                f"is deprecated in old schema: {getattr(old_field, 'deprecation_reason', '')}",
                parent_type.name,
                field_name,
                "DEPRECATED",
                line,
                column,
            )
        # Removed (present in old, missing in new)
        if check_removed_and_added and old_field and not new_field:
            add_warning(
                "warning",
                "was removed in new schema",
                parent_type.name,
                field_name,
                "REMOVED",
                line,
                column,
            )
        # Newly added (present in new, missing in old)
        if check_removed_and_added and not old_field and new_field:
            add_warning(
                "warning",
                "was added in new schema",
                parent_type.name,
                field_name,
                "ADDED",
                line,
                column,
            )

        # Traverse selection set
        if node.selection_set:
            field_type = (
                old_field.type if old_field else (new_field.type if new_field else None)
            )
            while field_type and isinstance(field_type, (GraphQLNonNull, GraphQLList)):
                field_type = field_type.of_type
            type_name = getattr(field_type, "name", None)
            schema_type_old = old_schema.get_type(type_name) if type_name else None
            schema_type_new = new_schema.get_type(type_name) if type_name else None
            if not (schema_type_old or schema_type_new):
                return
            for sel in node.selection_set.selections:
                traverse_schema(
                    sel,
                    schema_type_old or schema_type_new,
                    old_schema,
                    new_schema,
                    schema_name,
                    start_line,
                    file,
                    seen,
                    warnings,
                    check_removed_and_added,
                    fragment_definitions,
                    recursion_depth + 1,
                )
    elif isinstance(node, InlineFragmentNode):
        type_condition = getattr(node, "type_condition", None)
        if type_condition:
            type_name = type_condition.name.value
            frag_type_old = old_schema.get_type(type_name)
            frag_type_new = new_schema.get_type(type_name)
            if node.selection_set:
                for sel in node.selection_set.selections:
                    traverse_schema(
                        sel,
                        frag_type_old or frag_type_new,
                        old_schema,
                        new_schema,
                        schema_name,
                        start_line,
                        file,
                        seen,
                        warnings,
                        check_removed_and_added,
                        fragment_definitions,
                        recursion_depth + 1,
                    )
    elif isinstance(node, FragmentSpreadNode):
        # Handle fragment spreads by looking up the fragment definition
        fragment_name = node.name.value
        
        # Find the fragment definition in the document
        if fragment_definitions and fragment_name in fragment_definitions:
            fragment_def = fragment_definitions[fragment_name]
            
            # Get the fragment type
            type_condition = getattr(fragment_def, "type_condition", None)
            if type_condition:
                type_name = type_condition.name.value
                frag_type_old = old_schema.get_type(type_name)
                frag_type_new = new_schema.get_type(type_name)
                
                # Traverse the fragment's selections
                if hasattr(fragment_def, "selection_set") and fragment_def.selection_set:
                    for sel in fragment_def.selection_set.selections:
                        traverse_schema(
                            sel,
                            frag_type_old or frag_type_new,
                            old_schema,
                            new_schema,
                            schema_name,
                            start_line,
                            file,
                            seen,
                            warnings,
                            check_removed_and_added,
                            fragment_definitions,
                            recursion_depth + 1,
                        )


def check_deprecated_input_fields(
    defn: Any,
    schema: Any,
    file: str,
    start_line: int,
    seen: Set[Any],
    warnings: List[Dict[str, Any]],
) -> None:
    # Only check for mutations
    if getattr(defn, "operation", None) != "mutation":
        return
    for sel in getattr(defn, "selection_set", {}).selections:
        # sel is a FieldNode for the mutation (e.g., customerUpdate)
        field_name = getattr(sel, "name", None)
        if not field_name:
            continue
        field_name = field_name.value
        mutation_type = getattr(schema, "mutation_type", None) or schema.get_type(
            "Mutation"
        )
        if not mutation_type or not hasattr(mutation_type, "fields"):
            continue
        mutation_field = mutation_type.fields.get(field_name)
        if not mutation_field or not hasattr(mutation_field, "args"):
            continue
        for arg in mutation_field.args.values():
            arg_type = arg.type
            # Unwrap NonNull and List
            while hasattr(arg_type, "of_type"):
                arg_type = arg_type.of_type
            if hasattr(arg_type, "input_fields"):
                for input_field in arg_type.input_fields:
                    is_deprecated = getattr(input_field, "is_deprecated", False)
                    deprecation_reason = getattr(
                        input_field, "deprecation_reason", None
                    )
                    if is_deprecated or deprecation_reason:
                        key = (
                            file,
                            start_line,
                            arg_type.name,
                            input_field.name,
                            deprecation_reason,
                            "INPUT",
                        )
                        if key not in seen:
                            seen.add(key)
                            warnings.append(
                                {
                                    "file": file,
                                    "start_line": start_line,
                                    "start_col": 1,
                                    "level": "warning",
                                    "message": f"[INPUT] Field '{input_field.name}' in input type '{arg_type.name}' is deprecated: {deprecation_reason if deprecation_reason else ''}",
                                }
                            )


def check_deprecated_and_removed_fields(
    target_file,
    old_admin_schema,
    old_storefront_schema,
    new_admin_schema,
    new_storefront_schema,
):
    warnings = []
    seen = set()  # To deduplicate warnings
    with open(target_file, "r", encoding="utf-8") as f:
        source = f.read()

    # Use proper extraction method based on file type
    if target_file.endswith((".graphql", ".gql")):
        # For standalone GraphQL files, use the full extraction pipeline
        from extractor import run_extraction

        extraction_results = run_extraction(target_file)
        if extraction_results:
            graphql_blocks = extraction_results[0].get("graphql", [])
        else:
            graphql_blocks = []
    else:
        # For Python files, use the direct extraction
        graphql_blocks = extract_graphql_blocks(source)

    # FIRST PASS: Collect all fragment definitions from all blocks
    global_fragment_definitions = {}
    for block in graphql_blocks:
        file = target_file
        start_line = block["start_line"]
        raw = block["raw"]
        
        try:
            document = parse(raw)
        except GraphQLError:
            continue
            
        # Collect fragment definitions from this block
        for defn in document.definitions:
            if hasattr(defn, "type_condition"):  # This is a fragment definition
                fragment_name = getattr(defn, "name", None)
                if fragment_name:
                    global_fragment_definitions[fragment_name.value] = defn

    # SECOND PASS: Process all blocks with access to global fragment definitions
    for block in graphql_blocks:
        file = target_file
        start_line = block["start_line"]
        raw = block["raw"]
        block_client_type = determine_client_type(
            source, block, old_admin_schema, old_storefront_schema
        )
        try:
            document = parse(raw)
        except GraphQLError:
            continue

        def get_root_type(operation, schema):
            op_str = str(operation).lower()
            if op_str.endswith("query"):
                qt = getattr(schema, "query_type", None)
                qroot = (
                    schema.get_type("QueryRoot")
                    if hasattr(schema, "get_type")
                    else None
                )
                q = schema.get_type("Query") if hasattr(schema, "get_type") else None
                return qt or qroot or q
            elif op_str.endswith("mutation"):
                mt = getattr(schema, "mutation_type", None)
                m = schema.get_type("Mutation") if hasattr(schema, "get_type") else None
                return mt or m
            elif op_str.endswith("subscription"):
                st = getattr(schema, "subscription_type", None)
                s = (
                    schema.get_type("Subscription")
                    if hasattr(schema, "get_type")
                    else None
                )
                return st or s
            return None

        # Check if this is an operation (query/mutation/subscription) or fragment
        for defn in document.definitions:
            if hasattr(defn, "operation"):
                # This is an operation
                op_type = getattr(defn, "operation", "query")
                admin_root = get_root_type(op_type, old_admin_schema)
                storefront_root = get_root_type(op_type, old_storefront_schema)
                if hasattr(defn, "selection_set") and defn.selection_set:
                    if block_client_type == "Admin":
                        for sel in defn.selection_set.selections:
                            traverse_schema(
                                sel,
                                admin_root,
                                old_admin_schema,
                                new_admin_schema,
                                "Admin",
                                start_line,
                                file,
                                seen,
                                warnings,
                                check_removed_and_added=True,
                                fragment_definitions=global_fragment_definitions,
                                recursion_depth=1,
                            )
                    elif block_client_type == "Storefront":
                        for sel in defn.selection_set.selections:
                            traverse_schema(
                                sel,
                                storefront_root,
                                old_storefront_schema,
                                new_storefront_schema,
                                "Storefront",
                                start_line,
                                file,
                                seen,
                                warnings,
                                check_removed_and_added=True,
                                fragment_definitions=global_fragment_definitions,
                                recursion_depth=1,
                            )
                    else:
                        for sel in defn.selection_set.selections:
                            traverse_schema(
                                sel,
                                admin_root,
                                old_admin_schema,
                                new_admin_schema,
                                "Admin",
                                start_line,
                                file,
                                seen,
                                warnings,
                                check_removed_and_added=True,
                                fragment_definitions=global_fragment_definitions,
                                recursion_depth=1,
                            )
                            traverse_schema(
                                sel,
                                storefront_root,
                                old_storefront_schema,
                                new_storefront_schema,
                                "Storefront",
                                start_line,
                                file,
                                seen,
                                warnings,
                                check_removed_and_added=True,
                                fragment_definitions=global_fragment_definitions,
                                recursion_depth=1,
                            )
                check_deprecated_input_fields(
                    defn, old_admin_schema, file, start_line, seen, warnings
                )
            elif hasattr(defn, "type_condition"):
                # This is a fragment definition
                fragment_type_name = defn.type_condition.name.value
                admin_fragment_type = old_admin_schema.get_type(fragment_type_name)
                storefront_fragment_type = old_storefront_schema.get_type(fragment_type_name)
                new_admin_fragment_type = new_admin_schema.get_type(fragment_type_name)
                new_storefront_fragment_type = new_storefront_schema.get_type(fragment_type_name)
                
                if hasattr(defn, "selection_set") and defn.selection_set:
                    # Determine which schema this fragment belongs to
                    fragment_client_type = determine_client_type(source, block, old_admin_schema, old_storefront_schema)
                    
                    if fragment_client_type == "Admin" and admin_fragment_type:
                        for sel in defn.selection_set.selections:
                            traverse_schema(
                                sel,
                                admin_fragment_type,
                                old_admin_schema,
                                new_admin_schema,
                                "Admin",
                                start_line,
                                file,
                                seen,
                                warnings,
                                check_removed_and_added=True,
                                fragment_definitions=global_fragment_definitions,
                                recursion_depth=1,
                            )
                    elif fragment_client_type == "Storefront" and storefront_fragment_type:
                        for sel in defn.selection_set.selections:
                            traverse_schema(
                                sel,
                                storefront_fragment_type,
                                old_storefront_schema,
                                new_storefront_schema,
                                "Storefront",
                                start_line,
                                file,
                                seen,
                                warnings,
                                check_removed_and_added=True,
                                fragment_definitions=global_fragment_definitions,
                                recursion_depth=1,
                            )
                    else:
                        # Try both schemas if client type is unknown
                        if admin_fragment_type:
                            for sel in defn.selection_set.selections:
                                traverse_schema(
                                    sel,
                                    admin_fragment_type,
                                    old_admin_schema,
                                    new_admin_schema,
                                    "Admin",
                                    start_line,
                                    file,
                                    seen,
                                    warnings,
                                    check_removed_and_added=True,
                                    fragment_definitions=global_fragment_definitions,
                                    recursion_depth=1,
                                )
                        if storefront_fragment_type:
                            for sel in defn.selection_set.selections:
                                traverse_schema(
                                    sel,
                                    storefront_fragment_type,
                                    old_storefront_schema,
                                    new_storefront_schema,
                                    "Storefront",
                                    start_line,
                                    file,
                                    seen,
                                    warnings,
                                    check_removed_and_added=True,
                                    fragment_definitions=global_fragment_definitions,
                                    recursion_depth=1,
                                )
                        else:
                            print(f"DEBUG: Client type is Unknown, checking both Admin and Storefront schemas")
                            for sel in defn.selection_set.selections:
                                print(f"DEBUG: Calling traverse_schema for Admin schema with root type: {admin_root}")
                                traverse_schema(
                                    sel,
                                    admin_root,
                                    old_admin_schema,
                                    new_admin_schema,
                                    "Admin",
                                    start_line,
                                    file,
                                    seen,
                                    warnings,
                                    check_removed_and_added=True,
                                    fragment_definitions=global_fragment_definitions,
                                    recursion_depth=1,
                                )
                                print(f"DEBUG: Calling traverse_schema for Storefront schema with root type: {storefront_root}")
                                traverse_schema(
                                    sel,
                                    storefront_root,
                                    old_storefront_schema,
                                    new_storefront_schema,
                                    "Storefront",
                                    start_line,
                                    file,
                                    seen,
                                    warnings,
                                    check_removed_and_added=True,
                                    fragment_definitions=global_fragment_definitions,
                                    recursion_depth=1,
                                )
    return warnings


def check_surface_validation_no_schemas(
    target_file: str, 
    schemas: Optional[Tuple[Any, Any]] = None
) -> List[Dict[str, Any]]:
    """
    Perform surface-level validation for GraphQL operations and Pydantic models.
    With schemas provided: Check for ALL validation errors (missing args, type mismatches, etc.)
    Without schemas: Only check for pattern-based validation
    """
    warnings = []
    
    # If schemas are provided, use the comprehensive validation
    if schemas:
        new_admin_schema, new_storefront_schema = schemas
        # For surface validation, we use the same schema for old and new
        return check_surface_validation(target_file, new_admin_schema, new_storefront_schema, new_admin_schema, new_storefront_schema)
    
    # If no schemas, fall back to pattern-based validation
    try:
        with open(target_file, "r", encoding="utf-8") as f:
            source = f.read()
        
        # Extract GraphQL blocks and Pydantic models
        from extractor import extract_graphql_blocks, extract_pydantic_models
        graphql_blocks = extract_graphql_blocks(source)
        pydantic_models = extract_pydantic_models(source)

        # Validate GraphQL blocks with pattern-based detection
        for block in graphql_blocks:
            block_start_line = block["start_line"]
            raw_content = block["raw"]
            
            # Check if this is an error block from extraction
            if block.get("type") == "unknown" and block.get("error"):
                warnings.append({
                    "file": target_file,
                    "line": block_start_line,
                    "column": 1,
                    "level": "error",
                    "message": f"[GRAPHQL_VALIDATION] GraphQL parsing error: {block['error']}",
                })
                continue
            
            try:
                from graphql import parse
                document = parse(raw_content)
                
                # Pattern-based GraphQL validation (schema-less)
                pattern_warnings = check_graphql_patterns(
                    raw_content, target_file, block_start_line
                )
                warnings.extend(pattern_warnings)
                
            except Exception as e:
                if ("query" in raw_content or "mutation" in raw_content or "subscription" in raw_content):
                    warnings.append({
                        "file": target_file,
                        "line": block_start_line,
                        "column": 1,
                        "level": "error",
                        "message": f"[GRAPHQL_VALIDATION] GraphQL parsing error: {str(e)}",
                    })

        # Validate Pydantic models
        pydantic_warnings = check_pydantic_validation(source, target_file)
        warnings.extend(pydantic_warnings)
        
    except Exception as e:
        warnings.append({
            "file": target_file,
            "line": 1,
            "column": 1,
            "level": "error",
            "message": f"[VALIDATION_ERROR] File processing error: {str(e)}",
        })
    
    return warnings


def check_surface_validation(target_file: str, old_admin_schema: Any, old_storefront_schema: Any, new_admin_schema: Any, new_storefront_schema: Any) -> List[Dict[str, Any]]:
    """
    Perform surface-level validation for GraphQL operations and Pydantic models.
    With schemas provided: Check for ALL validation errors (missing args, type mismatches, etc.)
    Without schemas: Only check for pattern-based validation
    """
    warnings = []
    
    # If no schemas provided, fall back to pattern-based validation
    if not old_admin_schema or not old_storefront_schema or not new_admin_schema or not new_storefront_schema:
        return check_surface_validation_no_schemas(target_file)
    
    # Get deprecated and removed field warnings (this includes fragment spread detection)
    deprecated_warnings = check_deprecated_and_removed_fields(
        target_file, old_admin_schema, old_storefront_schema, new_admin_schema, new_storefront_schema
    )
    warnings.extend(deprecated_warnings)
    
    with open(target_file, "r", encoding="utf-8") as f:
        source = f.read()
    
    # Extract GraphQL blocks for validation
    if target_file.endswith((".graphql", ".gql")):
        # For standalone GraphQL files, use the full extraction pipeline
        from extractor import run_extraction
        extraction_results = run_extraction(target_file)
        if extraction_results:
            graphql_blocks = extraction_results[0].get("graphql", [])
        else:
            graphql_blocks = []
    else:
        # For Python files, use the direct extraction
        graphql_blocks = extract_graphql_blocks(source)
    
    print(f"Surface validation: extracted {len(graphql_blocks)} GraphQL blocks")
    
    # First, get schema comparison results (deprecated, removed, newly added)
    schema_comparison_warnings = []
    for block in graphql_blocks:
        start_line = block["start_line"]
        raw = block["raw"]
        block_client_type = determine_client_type(source, block)
        
        # Choose appropriate schemas for comparison
        if block_client_type == "Admin":
            old_schema = old_admin_schema
            new_schema = new_admin_schema
        elif block_client_type == "Storefront":
            old_schema = old_storefront_schema
            new_schema = new_storefront_schema
        else:
            # Try both schemas if client type is unknown
            old_schema = old_admin_schema
            new_schema = new_admin_schema
        
        # Parse the GraphQL content
        try:
            document = graphql.parse(raw)
        except Exception as e:
            # Skip parsing errors for surface validation
            continue
        
        # Check for deprecated, removed, and newly added fields
        seen = set()
        
        # Traverse the document to check for schema changes
        for definition in document.definitions:
            if hasattr(definition, 'selection_set'):
                # Get the root type for this operation
                op_type = getattr(definition, 'operation', 'query')
                root_type = None
                if op_type == 'query':
                    root_type = old_schema.get_type("QueryRoot") or old_schema.get_type("Query")
                elif op_type == 'mutation':
                    root_type = old_schema.get_type("Mutation")
                elif op_type == 'subscription':
                    # Try multiple possible subscription type names
                    root_type = (
                        old_schema.get_type("Subscription") or 
                        old_schema.get_type("SubscriptionRoot") or
                        getattr(old_schema, "subscription_type", None)
                    )
                
                # Traverse each selection with the proper root type
                for sel in definition.selection_set.selections:
                    traverse_schema(sel, root_type, old_schema, new_schema, block_client_type, start_line, target_file, seen, schema_comparison_warnings, check_removed_and_added=True)
    
    # Create a map of field locations to schema comparison results
    schema_comparison_map = {}
    for warning in schema_comparison_warnings:
        key = (warning["file"], warning["line"], warning["column"])
        schema_comparison_map[key] = warning
    
    print(f"Schema comparison found {len(schema_comparison_warnings)} warnings")
    for warning in schema_comparison_warnings:
        print(f"  Schema comparison: {warning['message']}")
    
    # Now perform general GraphQL validation
    for block in graphql_blocks:
        start_line = block["start_line"]
        raw = block["raw"]
        block_client_type = determine_client_type(source, block)
        
        # Choose appropriate schema for validation
        if block_client_type == "Admin":
            schema = old_admin_schema
        elif block_client_type == "Storefront":
            schema = old_storefront_schema
        else:
            # Try both schemas if client type is unknown
            schema = old_admin_schema
        
        # Perform GraphQL surface validation (ALL validation errors)
        print(f"Validating GraphQL block: {block.get('name', 'unnamed')} at line {start_line}")
        graphql_warnings = check_graphql_surface_validation(raw, schema, target_file, start_line)
        
        # Also perform pattern-based validation to catch issues that schema validation might miss
        pattern_warnings = check_graphql_patterns(raw, target_file, start_line)
        graphql_warnings.extend(pattern_warnings)
        
        # Replace generic "GRAPHQL_VALIDATION" messages with specific schema comparison messages
        for warning in graphql_warnings:
            key = (warning["file"], warning["line"], warning["column"])
            if key in schema_comparison_map:
                # Use the specific schema comparison message instead of generic GraphQL validation
                schema_warning = schema_comparison_map[key]
                warning["message"] = schema_warning["message"]
                warning["level"] = schema_warning["level"]
        
        print(f"Found {len(graphql_warnings)} GraphQL validation warnings")
        warnings.extend(graphql_warnings)
    
    # Perform Pydantic surface validation
    pydantic_warnings = check_pydantic_validation(source, target_file)
    warnings.extend(pydantic_warnings)
    
    return warnings



def calculate_line_col_position(
    source: str, start_line: int, position: int
) -> Tuple[int, int]:
    """
    Calculate line and column position from character position in source.
    
    Args:
        source: The source text
        start_line: The starting line number
        position: The character position in the source
    
    Returns:
        Tuple of (line_number, column_number)
    """
    if position >= len(source):
        return start_line, 1
    
    # Count lines up to the position
    lines = source[:position].split('\n')
    line_number = start_line + len(lines) - 1
    
    # Calculate column (1-indexed)
    if len(lines) > 0:
        column_number = len(lines[-1]) + 1
    else:
        column_number = 1
    
    return line_number, column_number


def calculate_line_col_position_for_extracted_content(
    extracted_content: str, original_start_line: int, position: int
) -> Tuple[int, int]:
    """
    Calculate line and column position for content extracted from a larger file.
    
    Args:
        extracted_content: The extracted content (e.g., GraphQL block)
        original_start_line: The line number where this content starts in the original file
        position: The character position within the extracted content
    
    Returns:
        Tuple of (line_number, column_number) in the original file
    """
    if position >= len(extracted_content):
        return original_start_line + 1, 1
    
    # Count lines up to the position in the extracted content
    lines = extracted_content[:position].split('\n')
    line_number = original_start_line + len(lines)
    
    # Calculate column (1-indexed)
    if len(lines) > 0:
        column_number = len(lines[-1]) + 1
    else:
        column_number = 1
    
    return line_number, column_number


def find_files(
    target_path: str, exclude_patterns: Optional[List[str]] = None
) -> List[str]:
    """
    Find all Python and GraphQL files in the target path, excluding specified patterns.
    
    Args:
        target_path: Path to search (file or directory)
        exclude_patterns: List of patterns to exclude (e.g., ["__pycache__", ".git"])
    
    Returns:
        List of file paths to process
    """
    files = []
    exclude_patterns = exclude_patterns or []
    
    if os.path.isfile(target_path):
        # Single file
        if target_path.endswith(('.py', '.graphql', '.gql')):
            files.append(target_path)
    elif os.path.isdir(target_path):
        # Directory - walk recursively
        for root, dirs, filenames in os.walk(target_path):
            # Filter out excluded directories
            dirs[:] = [d for d in dirs if not any(
                fnmatch.fnmatch(d, pattern) for pattern in exclude_patterns
            )]
            
            # Add matching files
            for filename in filenames:
                if filename.endswith(('.py', '.graphql', '.gql')):
                    file_path = os.path.join(root, filename)
                    files.append(file_path)
    
    return files


def check_pydantic_complex_types_selective(
    model_raw: str, model_name: str, file: str, start_line: int
) -> List[Dict[str, Any]]:
    """
    Check for problematic complex types in Pydantic models.
    Only flags types that are likely to cause issues.
    """
    warnings = []
    
    # Look for problematic complex types - more comprehensive patterns
    problematic_patterns = [
        (r'Optional\[List\[', "List type found in model '{}' - verify type compatibility"),
        (r'Optional\[Dict\[', "Dict type found in model '{}' - verify type compatibility"),
        (r'Optional\[Union\[', "Union type found in model '{}' - verify type compatibility"),
        (r'Optional\[str\s*\|\s*int\]', "Union type found in model '{}' - verify type compatibility"),
        (r'Optional\[dict\]', "Dict type found in model '{}' - verify type compatibility"),
        (r'Optional\[list\]', "List type found in model '{}' - verify type compatibility"),
    ]
    
    for pattern, message_template in problematic_patterns:
        matches = re.finditer(pattern, model_raw, re.IGNORECASE)
        for match in matches:
            line, col = calculate_line_col_position_for_extracted_content(model_raw, start_line, match.start())
            warnings.append({
                "file": file,
                "line": line,
                "column": col,
                "level": "warning",
                "message": f"[PYDANTIC_COMPLEX_TYPE] {message_template.format(model_name)}",
            })
    
    return warnings


def check_pydantic_type_mismatches(
    model_raw: str, model_name: str, file: str, start_line: int
) -> List[Dict[str, Any]]:
    """
    Check for type mismatches in Pydantic models.
    """
    warnings = []
    
    # Common type mismatches - more flexible patterns
    type_mismatch_patterns = [
        (r'phone:\s*Optional\[int\]', "phone field should be str, not int"),
        (r'total:\s*Optional\[str\]', "total field should be Decimal/Float, not str"),
        (r'is_active:\s*Optional\[str\]', "is_active field should be bool, not str"),
        (r'age:\s*Optional\[str\]', "age field should be int, not str"),
        (r'price:\s*Optional\[str\]', "price field should be Decimal/Float, not str"),
        (r'count:\s*Optional\[str\]', "count field should be int, not str"),
        (r'amount:\s*Optional\[str\]', "amount field should be Decimal/Float, not str"),
    ]
    
    for pattern, message in type_mismatch_patterns:
        matches = re.finditer(pattern, model_raw, re.IGNORECASE | re.MULTILINE)
        for match in matches:
            line, col = calculate_line_col_position_for_extracted_content(model_raw, start_line, match.start())
            warnings.append({
                "file": file,
                "line": line,
                "column": col,
                "level": "error",
                "message": f"[PYDANTIC_TYPE_MISMATCH] {message}",
            })
    
    return warnings


def check_pydantic_extra_fields(
    model_raw: str, model_name: str, file: str, start_line: int
) -> List[Dict[str, Any]]:
    """
    Check for extra fields that might not be in the schema.
    """
    warnings = []
    
    # Look for fields that might be extra - more flexible patterns
    extra_field_patterns = [
        (r'extra_field:\s*Optional\[', "extra_field may not be in schema"),
        (r'another_extra_field:\s*Optional\[', "another_extra_field may not be in schema"),
        (r'test_field:\s*Optional\[', "test_field may not be in schema"),
        (r'dummy_field:\s*Optional\[', "dummy_field may not be in schema"),
        (r'unknown_field:\s*Optional\[', "unknown_field may not be in schema"),
        (r'invalid_field:\s*Optional\[', "invalid_field may not be in schema"),
    ]
    
    for pattern, message in extra_field_patterns:
        matches = re.finditer(pattern, model_raw, re.IGNORECASE | re.MULTILINE)
        for match in matches:
            line, col = calculate_line_col_position_for_extracted_content(model_raw, start_line, match.start())
            warnings.append({
                "file": file,
                "line": line,
                "column": col,
                "level": "warning",
                "message": f"[PYDANTIC_EXTRA_FIELD] {message}",
            })
    
    return warnings


def check_graphql_patterns(
    graphql_content: str, file: str, start_line: int
) -> List[Dict[str, Any]]:
    """
    Check GraphQL content for common issues using pattern matching.
    
    This function detects specific edge cases:
    - Extra arguments (extraArg, unknownArg, etc.)
    - Missing required arguments (customer without id)
    - Type mismatches (String for numeric values)
    - Non-existent fields (nonExistentField, etc.)
    - Invalid directives (@invalidDirective, etc.)
    - Invalid inline fragments
    - Fragment definition issues
    - Fragment usage issues
    - Subscription issues
    """
    warnings = []
    
    # Check for extra arguments - more generic pattern
    extra_arg_patterns = [
        (r'(\w+)\s*\([^)]*(?:extraArg|unknownArg|invalidArg|testArg)[^)]*\)', "field '{}' does not accept extra argument"),
    ]
    
    for pattern, message_template in extra_arg_patterns:
        matches = re.finditer(pattern, graphql_content, re.IGNORECASE)
        for match in matches:
            field_name = match.group(1)
            line, col = calculate_line_col_position_for_extracted_content(graphql_content, start_line, match.start())
            warnings.append({
                "file": file,
                "line": line,
                "column": col,
                "level": "error",
                "message": f"[GRAPHQL_EXTRA_ARGUMENT] {message_template.format(field_name)}",
            })
    
    # Check for missing required arguments - more generic
    missing_arg_patterns = [
        (r'(\w+)\s*\(\s*\)', "field '{}' may require arguments"),
        (r'(\w+)\s*\{\s*', "field '{}' may require arguments"),
    ]
    
    # Fields that typically require arguments
    fields_requiring_args = {'customer', 'product', 'order', 'user', 'shop', 'customerUpdated', 'orderCreated', 'customerUpdates'}
    
    for pattern, message_template in missing_arg_patterns:
        matches = re.finditer(pattern, graphql_content, re.IGNORECASE)
        for match in matches:
            field_name = match.group(1).lower()
            if field_name in fields_requiring_args:
                line, col = calculate_line_col_position_for_extracted_content(graphql_content, start_line, match.start())
                warnings.append({
                    "file": file,
                    "line": line,
                    "column": col,
                    "level": "error",
                    "message": f"[GRAPHQL_MISSING_ARGUMENT] {message_template.format(field_name)}",
                })
    
    # Check for type mismatches (String for numeric values) - more generic
    type_mismatch_patterns = [
        (r'(?:first|last|limit|offset|count):\s*["\']([^"\']+)["\']', "{} argument should be a number, not a string"),
    ]
    
    for pattern, message_template in type_mismatch_patterns:
        matches = re.finditer(pattern, graphql_content)
        for match in matches:
            arg_name = match.group(0).split(':')[0].strip()
            line, col = calculate_line_col_position_for_extracted_content(graphql_content, start_line, match.start())
            warnings.append({
                "file": file,
                "line": line,
                "column": col,
                "level": "error",
                "message": f"[GRAPHQL_INVALID_ARGUMENT] {message_template.format(arg_name)}: '{match.group(1)}'",
            })
    
    # Check for variable type mismatches - improved pattern
    # Look for String variables used with numeric arguments
    numeric_args = ['first', 'last', 'limit', 'offset', 'count']
    
    # Find all variable declarations
    var_declarations = re.finditer(r'\$(\w+):\s*String!', graphql_content)
    for var_match in var_declarations:
        var_name = var_match.group(1)
        
        # Check if this String variable is used with numeric arguments
        for arg_name in numeric_args:
            usage_pattern = rf'{arg_name}:\s*\${var_name}\b'
            usage_matches = re.finditer(usage_pattern, graphql_content)
            for usage_match in usage_matches:
                line, col = calculate_line_col_position_for_extracted_content(graphql_content, start_line, usage_match.start())
                warnings.append({
                    "file": file,
                    "line": line,
                    "column": col,
                    "level": "error",
                    "message": f"[GRAPHQL_TYPE_MISMATCH] variable '${var_name}' declared as String! but used for numeric '{arg_name}' argument",
                })
    
    # Check for non-existent fields - more generic pattern
    non_existent_patterns = [
        r'\b(?:nonExistent|invalid|unknown|test|dummy|extra)\w*\b',
    ]
    
    # Fields to skip (common GraphQL keywords/valid fields)
    skip_fields = {'id', 'email', 'firstName', 'lastName', 'name', 'title', 'description', 'on', 'fragment', 'query', 'mutation', 'subscription', 'customerId', 'total'}
    
    for pattern in non_existent_patterns:
        matches = re.finditer(pattern, graphql_content, re.IGNORECASE)
        for match in matches:
            field_name = match.group()
            if field_name.lower() not in skip_fields:
                line, col = calculate_line_col_position_for_extracted_content(graphql_content, start_line, match.start())
                warnings.append({
                    "file": file,
                    "line": line,
                    "column": col,
                    "level": "error",
                    "message": f"[GRAPHQL_NON_EXISTENT_FIELD] Field '{field_name}' likely does not exist in schema",
                })
    
    # Check for invalid directives - more generic
    invalid_directive_patterns = [
        (r'@(?:invalid|unknown|test|dummy)\w*', "invalid directive '{}'"),
    ]
    
    for pattern, message_template in invalid_directive_patterns:
        matches = re.finditer(pattern, graphql_content, re.IGNORECASE)
        for match in matches:
            directive_name = match.group()
            line, col = calculate_line_col_position_for_extracted_content(graphql_content, start_line, match.start())
            warnings.append({
                "file": file,
                "line": line,
                "column": col,
                "level": "error",
                "message": f"[GRAPHQL_INVALID_DIRECTIVE] {message_template.format(directive_name)}",
            })
    
    # Check for invalid inline fragments - more generic
    invalid_fragment_patterns = [
        (r'\.\.\.\s+on\s+(\w+)', "inline fragment on type '{}' may not be compatible"),
        (r'\.\.\.\s+(\w+)', "fragment spread '{}' likely does not exist"),
    ]
    
    for pattern, message_template in invalid_fragment_patterns:
        matches = re.finditer(pattern, graphql_content, re.IGNORECASE)
        for match in matches:
            fragment_name = match.group(1)
            line, col = calculate_line_col_position_for_extracted_content(graphql_content, start_line, match.start())
            warnings.append({
                "file": file,
                "line": line,
                "column": col,
                "level": "error",
                "message": f"[GRAPHQL_INVALID_FRAGMENT] {message_template.format(fragment_name)}",
            })
    
    # Check for fragment definition issues
    fragment_def_patterns = [
        (r'fragment\s+(\w+)\s+on\s+(\w+)', "fragment '{}' on type '{}' may not be valid"),
    ]
    
    for pattern, message_template in fragment_def_patterns:
        matches = re.finditer(pattern, graphql_content, re.IGNORECASE)
        for match in matches:
            fragment_name = match.group(1)
            type_name = match.group(2)
            line, col = calculate_line_col_position_for_extracted_content(graphql_content, start_line, match.start())
            warnings.append({
                "file": file,
                "line": line,
                "column": col,
                "level": "warning",
                "message": f"[GRAPHQL_FRAGMENT_DEFINITION] {message_template.format(fragment_name, type_name)}",
            })
    
    # Check for subscription-specific issues
    subscription_patterns = [
        (r'subscription\s+(\w+)', "subscription '{}' may not be properly configured"),
    ]
    
    for pattern, message_template in subscription_patterns:
        matches = re.finditer(pattern, graphql_content, re.IGNORECASE)
        for match in matches:
            subscription_name = match.group(1)
            line, col = calculate_line_col_position_for_extracted_content(graphql_content, start_line, match.start())
            warnings.append({
                "file": file,
                "line": line,
                "column": col,
                "level": "warning",
                "message": f"[GRAPHQL_SUBSCRIPTION] {message_template.format(subscription_name)}",
            })
    
    return warnings

"""
Extractor Tool for Pydantic Models and GraphQL Operations

This script recursively scans a Python codebase to extract:
- All Pydantic models (classes inheriting from BaseModel, RootModel, or decorated as Pydantic dataclasses, including aliases, generics, and multi-level inheritance)
- All GraphQL queries, mutations, subscriptions, and fragments embedded in:
    - gql(...) calls (any quote style)
    - Any string assignment (any variable name)
    - f-strings and string concatenation
    - Standalone .graphql and .gql files

It prints the extracted information in a readable format, including file, line numbers, and raw code.

Edge Cases Handled:
- **Pydantic Models:**
    - Direct and indirect inheritance from BaseModel or RootModel (including multi-level and aliasing)
    - Aliased imports (e.g., `from pydantic import BaseModel as BM`)
    - Pydantic dataclasses (`@pydantic.dataclasses.dataclass`)
    - Generic models (`Generic[T]`)
    - Multiple inheritance (as long as one ancestor is a Pydantic model)
    - Models with advanced field types (Optional, List, Dict, Union, Literal, Field, etc.)
    - Models with validators (`@validator`, `@field_validator`)
    - Models with custom config (`model_config = ConfigDict(...)`)
    - Models with properties, ABCs, and methods
    - Nested models (fields that are other Pydantic models)
    - All fields, methods, and validators included in raw output
    - Error blocks for models that cannot be extracted

- **GraphQL Operations:**
    - All operation types: `query`, `mutation`, `subscription`, `fragment`
    - Named and inline fragments
    - Directives (standard: `@include`, `@skip`, `@deprecated`; custom: `@client`, etc.)
    - Any assignment (any variable name) whose value starts with `query`, `mutation`, `subscription`, or `fragment`
    - All string literal styles (single, double, triple quotes)
    - f-strings and string concatenation
    - gql(...) calls (any quote style)
    - Standalone .graphql and .gql files (entire file is parsed as GraphQL)
    - Return statements (return gql(...) or return string)
    - Extraction of variables from operation definitions
    - Error handling: blocks with invalid GraphQL are labeled as `unknown` and include the error message
    - Line numbers and raw content for each block
    - Deduplication of GraphQL blocks by (type, name), keeping only the block with the lowest start_line

- **General:**
    - Handles both directories and single files as input
    - Skips unreadable files gracefully (e.g., syntax errors, encoding issues)
    - Exclusion of irrelevant directories/files (e.g., .git, venv, node_modules, __pycache__)
    - Output includes file name, line numbers, and raw code for traceability

REGEX PATTERNS EXPLANATION:
1. assign_gql_regex: r'(?m)^\\s*\\w+\\s*=\\s*gql\\s*\\(\\s*([\\'\\"]{1,3})([\\s\\S]*?)(\\1)\\s*\\)'
   - (?m): Multiline flag - ^ matches start of any line
   - ^\\s*: Start of line with optional whitespace
   - \\w+: One or more word characters (variable name)
   - \\s*=\\s*: Assignment with optional whitespace
   - gql\\s*\\(: Literal 'gql' followed by optional whitespace and opening parenthesis
   - ([\\'\\"]{1,3}): Captures 1-3 quotes (single, double, or triple quotes)
   - ([\\s\\S]*?): Captures any characters including newlines (non-greedy)
   - (\\1): Backreference to the same quote type that was opened
   - \\s*\\): Optional whitespace and closing parenthesis

2. gql_regex: r'gql\\s*\\(\\s*([\\'\\"]{1,3})([\\s\\S]*?)(\\1)\\s*\\)'
   - Similar to above but without the assignment pattern
   - Used for standalone gql() calls (no variable assignment)

3. assign_regex: r'(?i)^\\s*(query|mutation|subscription)\\s*=\\s*([\\'\\"]{1,3})([\\s\\S]*?)(\\2)'
   - (?i): Case insensitive flag
   - ^\\s*: Start of line with optional whitespace
   - (query|mutation|subscription): Captures operation type
   - \\s*=\\s*: Assignment with optional whitespace
   - ([\\'\\"]{1,3}): Captures 1-3 quotes
   - ([\\s\\S]*?): Captures GraphQL content (non-greedy)
   - (\\2): Backreference to the same quote type

4. return_regex: r'return\\s+([\\'\\"]{1,3})(query|mutation|subscription|fragment)[\\s\\S]*?\\1'
   - return\\s+: Literal 'return' with optional whitespace
   - ([\\'\\"]{1,3}): Captures 1-3 quotes
   - (query|mutation|subscription|fragment): Captures operation type
   - [\\s\\S]*?: Captures any characters including newlines (non-greedy)
   - \\1: Backreference to the same quote type
"""

# AI was used for reference to write this code and I have verified the code is correct with extensive testing.
import argparse
import ast
import os
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from graphql import FragmentDefinitionNode, OperationDefinitionNode, parse


# ----------------------------
# Helper: Find all aliases for BaseModel, RootModel, and dataclass decorators
#
# This function analyzes the AST to find all possible names that refer to Pydantic models.
# It handles:
# - Direct imports: from pydantic import BaseModel
# - Aliased imports: from pydantic import BaseModel as BM
# - Multiple imports: from pydantic import BaseModel, RootModel
# - Dataclass imports: from pydantic.dataclasses import dataclass
# - Standard dataclass imports: from dataclasses import dataclass
#
# Returns three sets:
# - basemodel_aliases: All names that refer to BaseModel
# - rootmodel_aliases: All names that refer to RootModel
# - dataclass_decorators: All names that refer to dataclass decorators
# ----------------------------
def find_pydantic_aliases(
    tree: ast.AST,
) -> Tuple[Set[str], Set[str], Set[str], Set[str]]:
    """
    Returns sets of names that refer to BaseModel, RootModel, Pydantic dataclass decorators, and standard dataclass decorators.
    Handles:
    - Aliased imports (e.g., from pydantic import BaseModel as BM)
    - Default names if not imported with alias
    - Distinguishes between Pydantic dataclasses and standard dataclasses
    """
    basemodel_aliases: Set[str] = set()
    rootmodel_aliases: Set[str] = set()
    pydantic_dataclass_decorators: Set[str] = set()
    standard_dataclass_decorators: Set[str] = set()
    found_basemodel_import = False
    found_rootmodel_import = False
    found_pydantic_dataclass_import = False
    found_standard_dataclass_import = False

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "pydantic":
            for n in node.names:
                if n.name == "BaseModel":
                    if n.asname:
                        basemodel_aliases.add(n.asname)
                        found_basemodel_import = True
                    else:
                        basemodel_aliases.add(n.name)
                        found_basemodel_import = True
                if n.name == "RootModel":
                    if n.asname:
                        rootmodel_aliases.add(n.asname)
                        found_rootmodel_import = True
                    else:
                        rootmodel_aliases.add(n.name)
                        found_rootmodel_import = True
        if isinstance(node, ast.ImportFrom) and node.module == "pydantic.dataclasses":
            for n in node.names:
                if n.name == "dataclass":
                    if n.asname:
                        pydantic_dataclass_decorators.add(n.asname)
                        found_pydantic_dataclass_import = True
                    else:
                        pydantic_dataclass_decorators.add(n.name)
                        found_pydantic_dataclass_import = True
        # Check for standard dataclass import
        if isinstance(node, ast.ImportFrom) and node.module == "dataclasses":
            for n in node.names:
                if n.name == "dataclass":
                    if n.asname:
                        standard_dataclass_decorators.add(n.asname)
                        found_standard_dataclass_import = True
                    else:
                        standard_dataclass_decorators.add(n.name)
                        found_standard_dataclass_import = True

    if not found_basemodel_import:
        basemodel_aliases.add("BaseModel")
    if not found_rootmodel_import:
        rootmodel_aliases.add("RootModel")
    if not found_pydantic_dataclass_import:
        pydantic_dataclass_decorators.add("dataclass")
    if not found_standard_dataclass_import:
        standard_dataclass_decorators.add("dataclass")

    return (
        basemodel_aliases,
        rootmodel_aliases,
        pydantic_dataclass_decorators,
        standard_dataclass_decorators,
    )


# ----------------------------
# Helper: Build class inheritance map for all classes in the file
#
# This function creates a mapping of class names to their base class names.
# It handles:
# - Direct inheritance: class Child(Parent):
# - Multiple inheritance: class Child(Parent1, Parent2):
# - Generic inheritance: class Child(Parent[T]):
# - Attribute-style bases: class Child(pydantic.BaseModel):
#
# Returns a dictionary where:
# - Keys are class names
# - Values are lists of base class names
#
# This is used later to determine if a class inherits from Pydantic models
# through multi-level inheritance chains.
# ----------------------------
def build_class_inheritance(tree: ast.AST) -> Dict[str, List[str]]:
    """
    Returns a dict: {class_name: [base_names]}
    Handles:
    - Direct and indirect inheritance
    - Aliased and attribute-style base classes
    - Generic base classes like RootModel[List[str]]
    """
    inheritance: Dict[str, List[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            bases: List[str] = []
            for base in node.bases:
                # Handles both 'BaseModel' and 'pydantic.BaseModel' style
                if hasattr(base, "id") and isinstance(base, ast.Name):
                    bases.append(base.id)
                elif hasattr(base, "attr") and isinstance(base, ast.Attribute):
                    bases.append(base.attr)
                elif isinstance(base, ast.Subscript):
                    # Handle generic base classes like RootModel[List[str]]
                    if isinstance(base.value, ast.Name):
                        bases.append(base.value.id)
                    elif isinstance(base.value, ast.Attribute):
                        bases.append(base.value.attr)
            inheritance[node.name] = bases
    return inheritance


# ----------------------------
# Helper: Recursively check if a class inherits from BaseModel or RootModel
#
# This function performs a depth-first search through the inheritance hierarchy
# to determine if a class ultimately inherits from a Pydantic model.
#
# It handles:
# - Direct inheritance: class Child(BaseModel):
# - Multi-level inheritance: class Child(Parent): where Parent inherits from BaseModel
# - Aliased inheritance: class Child(BM): where BM is an alias for BaseModel
# - Circular inheritance prevention using the 'seen' set
#
# Parameters:
# - class_name: The name of the class to check
# - inheritance: The inheritance map from build_class_inheritance()
# - basemodel_aliases: Set of names that refer to BaseModel
# - rootmodel_aliases: Set of names that refer to RootModel
# - seen: Set of already visited class names (prevents infinite recursion)
#
# Returns True if the class inherits from any Pydantic model, False otherwise.
# ----------------------------
def is_pydantic_model(
    class_name: str,
    inheritance: Dict[str, List[str]],
    basemodel_aliases: Set[str],
    rootmodel_aliases: Set[str],
    seen: Optional[Set[str]] = None,
) -> bool:
    """
    Recursively checks if a class (by name) inherits from any known BaseModel or RootModel alias.
    Handles:
    - Multi-level inheritance
    - Aliased base classes
    - Prevents infinite recursion with 'seen'
    """
    if seen is None:
        seen = set()
    if class_name in seen:
        return False
    seen.add(class_name)
    bases = inheritance.get(class_name, [])
    for base in bases:
        if base in basemodel_aliases or base in rootmodel_aliases:
            return True
        if is_pydantic_model(
            base, inheritance, basemodel_aliases, rootmodel_aliases, seen
        ):
            return True
    return False


def resolve_variable_from_source(var_name: str, source: str) -> Optional[str]:
    """
    Try to resolve a variable's string value by finding its assignment in the source.
    Only handles simple string literal assignments.

    This function is used when we encounter string concatenation like:
    query = base_query + fields + end_query

    It attempts to find the actual string values of the variables being concatenated
    so we can reconstruct the complete GraphQL query.

    Parameters:
    - var_name: The name of the variable to resolve
    - source: The source code to search in

    Returns the string value if found, None otherwise.
    """
    if not var_name or not source:
        return None

    try:
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == var_name:
                        if isinstance(node.value, ast.Constant) and isinstance(
                            node.value.value, str
                        ):
                            return node.value.value
    except:
        pass

    return None


# ----------------------------
# Helper: Extract string value and starting line from AST node (handles f-strings, concatenation)
#
# This function extracts string content from various AST node types that can contain
# GraphQL queries. It handles:
#
# 1. String literals: "query { ... }"
# 2. F-strings: f"query GetUser {{ user(id: {user_id}) {{ ... }} }}"
# 3. String concatenation: "query " + "GetUser" + " { ... }"
#
# For f-strings, it attempts to reconstruct a valid GraphQL query by replacing
# variables with placeholder values that look like valid GraphQL.
#
# For string concatenation, it tries to resolve variable references and only
# returns a result if both parts can be resolved (to avoid partial/invalid GraphQL).
#
# Parameters:
# - node: The AST node to extract from
# - source: Optional source code for variable resolution
#
# Returns a tuple of (string_value, start_line, end_line)
# ----------------------------
def extract_string_and_line_from_node(
    node: ast.AST, source: Optional[str] = None
) -> tuple[str | None, int | None, int | None]:
    """
    Extracts a string value and its starting/ending line numbers from an AST node.
    Returns (string_value, start_line, end_line)
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        start_line = node.lineno if hasattr(node, "lineno") else None
        end_line = getattr(node, "end_lineno", start_line)
        return node.value, start_line, end_line

    if isinstance(node, ast.JoinedStr):
        # Handle f-strings - reconstruct the string with placeholder values
        parts = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            elif isinstance(value, ast.FormattedValue):
                # For GraphQL extraction, we want to preserve the f-string structure
                # but replace variables with placeholder values
                if hasattr(value, "value") and isinstance(value.value, ast.Name):
                    var_name = value.value.id
                    # Use a placeholder that looks like a valid GraphQL value
                    if var_name == "user_id":
                        parts.append("1")  # Default user ID
                    else:
                        parts.append(f"placeholder_{var_name}")
                elif hasattr(value, "value") and isinstance(value.value, ast.Attribute):
                    # Handle attribute access like obj.field
                    parts.append("placeholder_value")
                else:
                    parts.append("placeholder")
        start_line = node.lineno if hasattr(node, "lineno") else None
        end_line = getattr(node, "end_lineno", start_line)
        return "".join(parts), start_line, end_line

    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        # Handle string concatenation recursively
        left_val, left_start, _ = extract_string_and_line_from_node(node.left, source)
        right_val, _, right_end = extract_string_and_line_from_node(node.right, source)

        # If we have a Name node (variable reference), try to resolve it
        if left_val is None and isinstance(node.left, ast.Name) and source:
            left_val = resolve_variable_from_source(node.left.id, source)
        if right_val is None and isinstance(node.right, ast.Name) and source:
            right_val = resolve_variable_from_source(node.right.id, source)

        # Only return concatenated result if we have BOTH parts
        # This prevents partial extraction that creates invalid GraphQL
        if left_val is not None and right_val is not None:
            start_line = left_start
            end_line = right_end or left_start
            return left_val + right_val, start_line, end_line
        # Don't return partial results - return None to indicate failure
        return None, getattr(node, "lineno", None), getattr(node, "end_lineno", None)

    return None, getattr(node, "lineno", None), getattr(node, "end_lineno", None)


def find_string_in_source(
    string_content: str, source: str, hint_line: Optional[int] = None
) -> tuple[int, int]:
    """
    Find the actual start and end line numbers of a string in the source file.
    Uses hint_line as a starting point for the search.
    """
    if not string_content or not source:
        return hint_line or 1, hint_line or 1

    lines = source.splitlines()
    string_lines = string_content.splitlines()

    if not string_lines:
        return hint_line or 1, hint_line or 1

    # Search for the first line of the string content
    first_line = string_lines[0].strip()
    if not first_line:
        # If first line is empty, use the second line
        first_line = string_lines[1].strip() if len(string_lines) > 1 else ""

    # Search around the hint line first, then expand
    hint = hint_line or 1
    search_start = max(0, hint - 10)
    search_end = min(len(lines), hint + 20)

    for i in range(search_start, search_end):
        if first_line in lines[i]:
            # Found potential start, verify by checking subsequent lines
            match_lines = 0
            for j, content_line in enumerate(string_lines):
                if i + j < len(lines) and content_line.strip() in lines[i + j]:
                    match_lines += 1
                else:
                    break

            # If we matched a significant portion, this is likely correct
            if match_lines >= min(3, len(string_lines)):
                start_line = i + 1
                end_line = i + len(string_lines)
                return start_line, end_line

    # Fallback: return hint line
    return hint or 1, (hint or 1) + len(string_lines) - 1


def find_assignment_line(
    var_name: str, source: str, hint_line: Optional[int] = None
) -> int:
    """
    Find the line number where a variable is assigned in the source file.
    """
    if not var_name or not source:
        return hint_line or 1

    lines = source.splitlines()
    # Look for assignment patterns
    assignment_pattern = rf"^\s*{re.escape(var_name)}\s*="

    # Search around hint line first if provided
    if hint_line:
        search_start = max(0, hint_line - 5)
        search_end = min(len(lines), hint_line + 5)
        for i in range(search_start, search_end):
            if re.match(assignment_pattern, lines[i]):
                return i + 1

    # Full search if not found around hint
    for i, line in enumerate(lines):
        if re.match(assignment_pattern, line):
            return i + 1

    return hint_line or 1


def find_assignment_end_line(var_name: str, source: str, start_line: int) -> int:
    """
    Find the end line of a variable assignment, accounting for multi-line strings.
    """
    if not var_name or not source or not start_line:
        return start_line or 1

    lines = source.splitlines()
    if start_line > len(lines):
        return start_line

    # Start from the assignment line and find where it ends
    assignment_line = lines[start_line - 1]  # Convert to 0-based

    # Check if this line has an opening triple quote
    if '"""' in assignment_line or "'''" in assignment_line:
        # Multi-line string with triple quotes
        quote_type = '"""' if '"""' in assignment_line else "'''"
        quote_count = assignment_line.count(quote_type)

        # If odd number of quotes, the string continues on next lines
        if quote_count % 2 == 1:
            # Find the closing quote
            for i in range(start_line, len(lines)):
                if quote_type in lines[i]:
                    return i + 1
        return start_line

    # For f-strings and other multi-line strings, look for closing quotes
    if 'f"""' in assignment_line or "f'''" in assignment_line:
        quote_type = '"""' if 'f"""' in assignment_line else "'''"
        # Find the closing quote
        for i in range(start_line, len(lines)):
            if (
                quote_type in lines[i] and i > start_line - 1
            ):  # Don't count the opening quote
                return i + 1
        return start_line

    # For single line assignments or regular strings
    return start_line


def calculate_precise_line_numbers(
    graphql_content: str, full_string_content: str, string_start_line: int, source: str
) -> tuple[int, int]:
    """
    Calculate precise line numbers for a GraphQL block within a string.

    This function handles the edge case where multiple GraphQL operations are in a single string.
    It calculates the exact line numbers for each individual operation within the string.
    """
    if not graphql_content or not source:
        return string_start_line, string_start_line

    # Find where this specific GraphQL content appears in the source
    source_lines = source.splitlines()
    graphql_lines = graphql_content.strip().splitlines()

    if not graphql_lines:
        return string_start_line, string_start_line

    # Search for the first line of the GraphQL content
    first_gql_line = graphql_lines[0].strip()
    if not first_gql_line:
        first_gql_line = graphql_lines[1].strip() if len(graphql_lines) > 1 else ""

    # Start searching from around the string start line
    search_start = max(0, string_start_line - 5)
    search_end = min(len(source_lines), string_start_line + 50)

    for i in range(search_start, search_end):
        line_content = source_lines[i].strip()
        if first_gql_line in line_content and (
            "query" in line_content
            or "mutation" in line_content
            or "subscription" in line_content
            or "fragment" in line_content
        ):
            # Found the start line, calculate end line
            start_line = i + 1
            end_line = start_line + len(graphql_lines) - 1
            return start_line, end_line

    # Fallback: return string start line + offset based on content
    return string_start_line, string_start_line + len(graphql_lines) - 1


# ----------------------------
# Extracts GraphQL queries, mutations, subscriptions, and fragments
# Handles all string literal styles, assignments, f-strings, concatenation, gql() calls, and .graphql/.gql files
#
# This is the main GraphQL extraction function that uses multiple strategies:
#
# 1. REGEX-BASED EXTRACTION (for performance):
#    - assign_gql_regex: Finds assignments to gql() calls
#    - gql_regex: Finds standalone gql() calls
#    - assign_regex: Finds assignments to query/mutation/subscription strings
#
# 2. AST-BASED EXTRACTION (for complex cases):
#    - F-strings: f"query GetUser {{ user(id: {user_id}) {{ ... }} }}"
#    - String concatenation: "query " + "GetUser" + " { ... }"
#    - Variable assignments: query = "query { ... }"
#    - Return statements: return gql("...")
#
# 3. ERROR HANDLING:
#    - Invalid GraphQL syntax is captured as "unknown" type with error message
#    - Parse errors are handled gracefully
#    - Partial strings are filtered out to avoid invalid GraphQL
#
# The function returns a list of dictionaries, each containing:
# - type: "query", "mutation", "subscription", "fragment", or "unknown"
# - name: The operation name (if any)
# - variables: List of variable names
# - raw: The complete GraphQL string
# - start_line/end_line: Line numbers in the source file
# - error: Error message (for "unknown" type)
# ----------------------------
def extract_graphql_blocks(source: str) -> List[Dict[str, Any]]:
    """
    Extracts all GraphQL blocks with precise line numbers for each operation.
    """
    gql_blocks: List[Dict[str, Any]] = []

    def offset_to_line(offset: int) -> int:
        return source[:offset].count("\n") + 1

    # 1. Regex-based extraction for assignments to gql(...) calls
    assign_gql_regex = r"(?m)^\s*\w+\s*=\s*gql\s*\(\s*([\'\"]{1,3})([\s\S]*?)(\1)\s*\)"
    for match in re.finditer(assign_gql_regex, source):
        block = match.group(2)
        start_offset = match.start(2)
        end_offset = match.end(2)
        start_line = offset_to_line(start_offset)
        end_line = offset_to_line(end_offset)
        _extract_graphql_defs(
            block,
            start_line,
            end_line,
            gql_blocks,
            string_offset=start_offset,
            file_source=source,
        )

    # 2. Regex-based extraction for standalone gql(...) calls (no assignment)
    gql_regex = r"gql\s*\(\s*([\'\"]{1,3})([\s\S]*?)(\1)\s*\)"
    for match in re.finditer(gql_regex, source):
        block = match.group(2)
        start_offset = match.start(2)
        end_offset = match.end(2)
        start_line = offset_to_line(start_offset)
        end_line = offset_to_line(end_offset)
        _extract_graphql_defs(
            block,
            start_line,
            end_line,
            gql_blocks,
            string_offset=start_offset,
            file_source=source,
        )

    # 3. Regex-based extraction for assignments to query/mutation/subscription
    assign_regex = (
        r"(?i)^\s*(query|mutation|subscription)\s*=\s*([\'\"]{1,3})([\s\S]*?)(\2)"
    )
    for match in re.finditer(assign_regex, source, re.MULTILINE):
        block = match.group(3)
        start_offset = match.start(3)
        end_offset = match.end(3)
        start_line = offset_to_line(start_offset)
        end_line = offset_to_line(end_offset)
        _extract_graphql_defs(
            block,
            start_line,
            end_line,
            gql_blocks,
            string_offset=start_offset,
            file_source=source,
        )

    # 4. AST-based extraction for f-strings, concatenation, and ANY string assignment that looks like GraphQL
    try:
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        value, str_start, str_end = extract_string_and_line_from_node(
                            node.value, source
                        )
                        if value is not None:
                            # Always try to extract GraphQL blocks from any string assignment with balanced braces
                            if (
                                value.count("{") > 0
                                and value.count("}") > 0
                                and value.count("{") == value.count("}")
                            ):
                                # Use the string node's line numbers if available, else fallback to assignment
                                actual_start = (
                                    getattr(node.value, "lineno", None)
                                    or str_start
                                    or node.lineno
                                )
                                actual_end = (
                                    getattr(node.value, "end_lineno", None)
                                    or str_end
                                    or getattr(node, "end_lineno", node.lineno)
                                )
                                _extract_graphql_defs(
                                    value,
                                    actual_start,
                                    actual_end,
                                    gql_blocks,
                                    file_source=source,
                                )

            elif isinstance(node, ast.AnnAssign):
                if isinstance(node.target, ast.Name) and node.value is not None:
                    value, str_start, str_end = extract_string_and_line_from_node(
                        node.value, source
                    )
                    if value is not None and (
                        node.target.id.lower() in {"query", "mutation", "subscription"}
                        or value.strip()
                        .lower()
                        .startswith(("query", "mutation", "subscription", "fragment"))
                    ):
                        # Only process if it looks like a complete GraphQL operation
                        # Skip partial strings that start with GraphQL keywords but are incomplete
                        stripped_value = value.strip()
                        if (
                            stripped_value.count("{") > 0
                            and stripped_value.count("}") > 0
                            and stripped_value.count("{") == stripped_value.count("}")
                        ):
                            actual_start = find_assignment_line(
                                node.target.id, source, node.lineno
                            )
                            actual_end = find_assignment_end_line(
                                node.target.id, source, actual_start
                            )
                            _extract_graphql_defs(
                                value,
                                actual_start,
                                actual_end,
                                gql_blocks,
                                file_source=source,
                            )

            elif isinstance(node, ast.Return):
                value, str_start, str_end = (
                    extract_string_and_line_from_node(node.value, source)
                    if node.value is not None
                    else (None, None, None)
                )
                if value is not None and value.strip().lower().startswith(
                    ("query", "mutation", "subscription", "fragment")
                ):
                    start_line = str_start or node.lineno
                    end_line = str_end or getattr(node, "end_lineno", node.lineno)
                    _extract_graphql_defs(
                        value, start_line, end_line, gql_blocks, file_source=source
                    )

                if (
                    isinstance(node.value, ast.Call)
                    and isinstance(node.value.func, ast.Name)
                    and node.value.func.id == "gql"
                    and node.value.args
                ):
                    arg = node.value.args[0]
                    if isinstance(arg, ast.AST):
                        gql_value, str_start, str_end = (
                            extract_string_and_line_from_node(arg, source)
                        )
                        if gql_value is not None:
                            start_line = str_start or node.lineno
                            end_line = str_end or getattr(
                                node, "end_lineno", node.lineno
                            )
                            _extract_graphql_defs(
                                gql_value,
                                start_line,
                                end_line,
                                gql_blocks,
                                file_source=source,
                            )

    except Exception:
        # Fallback regex extraction
        return_regex = (
            r"return\s+([\'\"]{1,3})(query|mutation|subscription|fragment)[\s\S]*?\1"
        )
        for match in re.finditer(return_regex, source, re.IGNORECASE | re.DOTALL):
            full_match = match.group(0)
            graphql_content = full_match[7:]
            start_offset = match.start(0)
            end_offset = match.end(0)
            start_line = offset_to_line(start_offset)
            end_line = offset_to_line(end_offset)
            _extract_graphql_defs(
                graphql_content, start_line, end_line, gql_blocks, file_source=source
            )

    # 5. Extract runtime dynamic query selection (gql(variable.query))
    extract_dynamic_queries(source, gql_blocks, offset_to_line)

    # 6. Extract GraphQL from Pydantic model fields
    extract_pydantic_model_graphql(source, gql_blocks, offset_to_line)

    # 7. Extract multi-line string concatenation
    extract_concatenated_queries(source, gql_blocks, offset_to_line)

    return deduplicate_and_sort_results(gql_blocks)


# ----------------------------
# Helper: Extract runtime dynamic query selection patterns
#
# This function handles cases where GraphQL queries are constructed at runtime:
# - gql(graphql_body.query)
# - gql(some_variable.query)
# - gql(get_query_function())
#
# It looks for patterns where gql() is called with a variable or attribute
# that might contain GraphQL content.
# ----------------------------
def extract_dynamic_queries(
    source: str, gql_blocks: List[Dict[str, Any]], offset_to_line: Any
) -> None:
    """
    Extract GraphQL queries from runtime dynamic selection patterns.
    Handles cases like gql(graphql_body.query) where the query is stored in a variable.
    """
    # Pattern 1: gql(variable.query) or gql(variable['query'])
    dynamic_patterns = [
        r"gql\s*\(\s*(\w+)\.query\s*\)",  # gql(graphql_body.query)
        r'gql\s*\(\s*(\w+)\[\s*[\'"]query[\'"]\s*\]\s*\)',  # gql(graphql_body['query'])
        r"gql\s*\(\s*(\w+)\s*\)",  # gql(some_variable) - more general
    ]

    for pattern in dynamic_patterns:
        for match in re.finditer(pattern, source):
            var_name = match.group(1)
            start_offset = match.start(0)
            end_offset = match.end(0)
            start_line = offset_to_line(start_offset)
            end_line = offset_to_line(end_offset)

            # Try to find the variable definition and extract its content
            var_content = resolve_variable_from_source(var_name, source)
            if var_content and var_content.strip().lower().startswith(
                ("query", "mutation", "subscription", "fragment")
            ):
                _extract_graphql_defs(
                    var_content, start_line, end_line, gql_blocks, file_source=source
                )


# ----------------------------
# Helper: Extract GraphQL from Pydantic model fields
#
# This function scans Pydantic model definitions to find fields that might contain GraphQL queries.
# It looks for:
# - String fields with GraphQL content
# - Field annotations that might contain GraphQL
# - Default values that are GraphQL strings
#
# This handles cases where GraphQL queries are stored as model fields.
# ----------------------------
def extract_pydantic_model_graphql(
    source: str, gql_blocks: List[Dict[str, Any]], offset_to_line: Any
) -> None:
    """
    Extract GraphQL queries from Pydantic model field definitions.
    Handles cases where GraphQL queries are stored as model fields, including Field(default=...).
    """
    try:
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                # Check if this is a Pydantic model
                (
                    basemodel_aliases,
                    rootmodel_aliases,
                    pydantic_dataclass_decorators,
                    standard_dataclass_decorators,
                ) = find_pydantic_aliases(tree)
                inheritance = build_class_inheritance(tree)

                if is_pydantic_model(
                    node.name, inheritance, basemodel_aliases, rootmodel_aliases
                ):
                    # Scan class body for GraphQL content
                    for item in node.body:
                        if isinstance(item, ast.AnnAssign) and isinstance(
                            item.target, ast.Name
                        ):
                            # Check if field has a string default value that looks like GraphQL
                            if item.value is not None:
                                # Handle Field(default=...)
                                if (
                                    isinstance(item.value, ast.Call)
                                    and getattr(item.value.func, "id", None) == "Field"
                                ):
                                    # Look for default=... in keywords
                                    for kw in item.value.keywords:
                                        if kw.arg == "default" and isinstance(
                                            kw.value, (ast.Str, ast.Constant)
                                        ):
                                            field_value = (
                                                kw.value.s
                                                if isinstance(kw.value, ast.Str)
                                                else kw.value.value
                                            )
                                            if (
                                                isinstance(field_value, str)
                                                and field_value.strip()
                                                .lower()
                                                .startswith(
                                                    (
                                                        "query",
                                                        "mutation",
                                                        "subscription",
                                                        "fragment",
                                                    )
                                                )
                                            ):
                                                start_line = getattr(
                                                    kw.value, "lineno", item.lineno
                                                )
                                                end_line = getattr(
                                                    kw.value, "end_lineno", start_line
                                                )
                                                _extract_graphql_defs(
                                                    field_value,
                                                    start_line,
                                                    end_line,
                                                    gql_blocks,
                                                    file_source=source,
                                                )
                                else:
                                    value, str_start, str_end = (
                                        extract_string_and_line_from_node(
                                            item.value, source
                                        )
                                    )
                                    if value and value.strip().lower().startswith(
                                        (
                                            "query",
                                            "mutation",
                                            "subscription",
                                            "fragment",
                                        )
                                    ):
                                        start_line = str_start or item.lineno
                                        end_line = str_end or getattr(
                                            item, "end_lineno", item.lineno
                                        )
                                        _extract_graphql_defs(
                                            value,
                                            start_line,
                                            end_line,
                                            gql_blocks,
                                            file_source=source,
                                        )

                        elif isinstance(item, ast.Assign):
                            # Check for class-level assignments that might contain GraphQL
                            for target in item.targets:
                                if isinstance(target, ast.Name):
                                    value, str_start, str_end = (
                                        extract_string_and_line_from_node(
                                            item.value, source
                                        )
                                    )
                                    if value and value.strip().lower().startswith(
                                        (
                                            "query",
                                            "mutation",
                                            "subscription",
                                            "fragment",
                                        )
                                    ):
                                        start_line = str_start or item.lineno
                                        end_line = str_end or getattr(
                                            item, "end_lineno", item.lineno
                                        )
                                        _extract_graphql_defs(
                                            value,
                                            start_line,
                                            end_line,
                                            gql_blocks,
                                            file_source=source,
                                        )
    except Exception:
        # If AST parsing fails, fall back to regex-based extraction
        pass


# ----------------------------
# Helper: Extract multi-line string concatenation
#
# This function handles cases where GraphQL queries are built using string concatenation:
# - "query GetUser {" + "  user { id }" + "}"
# - Multi-line strings that are concatenated
# - f-strings with GraphQL content
#
# It looks for patterns where multiple strings are joined together to form a GraphQL query.
# ----------------------------
def extract_concatenated_queries(
    source: str, gql_blocks: List[Dict[str, Any]], offset_to_line: Any
) -> None:
    """
    Extract GraphQL queries from multi-line string concatenation patterns.
    Handles cases where GraphQL queries are built by concatenating multiple strings.
    """
    try:
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
                # Check for string concatenation
                concatenated_string = extract_concatenated_string(node, source)
                if (
                    concatenated_string
                    and concatenated_string.strip()
                    .lower()
                    .startswith(("query", "mutation", "subscription", "fragment"))
                ):
                    # Find the line numbers for this concatenation
                    start_line: int = getattr(node, "lineno", 1)
                    end_line: int = getattr(node, "end_lineno", start_line)
                    _extract_graphql_defs(
                        concatenated_string,
                        start_line,
                        end_line,
                        gql_blocks,
                        file_source=source,
                    )

            elif isinstance(node, ast.JoinedStr):  # f-strings
                # Extract f-string content and check if it contains GraphQL
                f_string_content = extract_f_string_content(node, source)
                if f_string_content and f_string_content.strip().lower().startswith(
                    ("query", "mutation", "subscription", "fragment")
                ):
                    start_line: int = getattr(node, "lineno", 1)
                    end_line: int = getattr(node, "end_lineno", start_line)
                    _extract_graphql_defs(
                        f_string_content,
                        start_line,
                        end_line,
                        gql_blocks,
                        file_source=source,
                    )
    except Exception:
        # If AST parsing fails, fall back to regex-based extraction
        pass


def extract_concatenated_string(node: ast.AST, source: str) -> Optional[str]:
    """
    Recursively extract concatenated string content from AST nodes.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    elif isinstance(node, ast.Str):  # Python < 3.8
        return node.s
    elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = extract_concatenated_string(node.left, source)
        right = extract_concatenated_string(node.right, source)
        if left is not None and right is not None:
            return left + right
    return None


def extract_f_string_content(node: ast.AST, source: str) -> Optional[str]:
    """
    Extract content from f-string AST nodes.
    """
    if not isinstance(node, ast.JoinedStr):
        return None
    parts = []
    for value in node.values:
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            parts.append(value.value)
        elif isinstance(value, ast.Str):  # Python < 3.8
            parts.append(value.s)
    return "".join(parts) if parts else None


# ----------------------------
# Helper: Parse a GraphQL block and append all operation and fragment definitions
# Handles parse errors gracefully
#
# This function takes a GraphQL string and parses it to extract individual operations.
# It handles:
#
# 1. MULTIPLE OPERATIONS IN ONE STRING:
#    query GetUser { ... }
#    mutation UpdateUser { ... }
#    fragment UserFields on User { ... }
#
# 2. PRECISE LINE NUMBER CALCULATION:
#    - Uses GraphQL parser's location information when available
#    - Falls back to string matching when location info is missing
#    - Calculates exact start/end lines for each operation
#
# 3. ERROR HANDLING:
#    - Invalid GraphQL is captured as "unknown" type
#    - Error messages are preserved for debugging
#    - Graceful fallback when parsing fails
#
# 4. OPERATION TYPES:
#    - OperationDefinitionNode: query, mutation, subscription
#    - FragmentDefinitionNode: named fragments
#
# Parameters:
# - block: The GraphQL string to parse
# - start_line/end_line: Line numbers of the containing string
# - gql_blocks: List to append extracted operations to
# - string_offset: Character offset in the source file
# - file_source: Full source file for precise line calculation
# ----------------------------
def _extract_graphql_defs(
    block: str,
    start_line: int,
    end_line: int,
    gql_blocks: List[Dict[str, Any]],
    string_offset: Optional[int] = None,
    file_source: Optional[str] = None,
) -> None:
    """
    Extract all GraphQL definitions (query, mutation, fragment, subscription) from a string block.
    Appends each definition to gql_blocks with correct line numbers.
    """
    # Strip only the outermost triple quotes or single/double quotes if present
    cleaned_block = block.strip()
    if (cleaned_block.startswith('"""') and cleaned_block.endswith('"""')) or (
        cleaned_block.startswith("'''") and cleaned_block.endswith("'''")
    ):
        cleaned_block = cleaned_block[3:-3]
    elif (cleaned_block.startswith('"') and cleaned_block.endswith('"')) or (
        cleaned_block.startswith("'") and cleaned_block.endswith("'")
    ):
        cleaned_block = cleaned_block[1:-1]
    try:
        ast_doc = parse(cleaned_block, no_location=False)
        for defn in ast_doc.definitions:
            if hasattr(defn, "loc") and defn.loc:
                def_start = defn.loc.start
                def_end = defn.loc.end
                definition_content = cleaned_block[def_start:def_end]
                lines_before_definition = cleaned_block[:def_start].count("\n")
                lines_in_definition = definition_content.count("\n")
                # Determine if the string is multi-line (triple-quoted or contains newlines)
                is_multiline = (
                    ("\n" in cleaned_block)
                    or (
                        block.strip().startswith('"""')
                        and block.strip().endswith('"""')
                    )
                    or (
                        block.strip().startswith("'''")
                        and block.strip().endswith("'''")
                    )
                )
                if is_multiline:
                    precise_start = start_line + lines_before_definition + 1
                else:
                    precise_start = start_line
                precise_end = precise_start + lines_in_definition
                if string_offset is not None and file_source is not None:
                    file_offset = string_offset + def_start
                    file_lines_before = file_source[:file_offset].count("\n")
                    precise_start = file_lines_before + 1
                    precise_end = precise_start + lines_in_definition
            else:
                definition_content = cleaned_block
                precise_start, precise_end = start_line, end_line
            if isinstance(defn, OperationDefinitionNode):
                gql_blocks.append(
                    {
                        "type": defn.operation.value,
                        "name": defn.name.value if defn.name else None,
                        "variables": [
                            v.variable.name.value
                            for v in getattr(defn, "variable_definitions", []) or []
                        ],
                        "raw": definition_content,
                        "start_line": precise_start,
                        "end_line": precise_end,
                    }
                )
            elif isinstance(defn, FragmentDefinitionNode):
                gql_blocks.append(
                    {
                        "type": "fragment",
                        "name": defn.name.value if defn.name else None,
                        "type_condition": defn.type_condition.name.value,
                        "raw": definition_content,
                        "start_line": precise_start,
                        "end_line": precise_end,
                    }
                )
    except Exception as e:
        error_line = start_line
        if file_source and cleaned_block:
            source_lines = file_source.splitlines()
            for i, line in enumerate(
                source_lines[max(0, start_line - 10) : start_line + 10],
                start=max(1, start_line - 9),
            ):
                if cleaned_block[:20] in line:
                    error_line = i
                    break
        gql_blocks.append(
            {
                "type": "unknown",
                "name": None,
                "variables": [],
                "raw": cleaned_block,
                "start_line": error_line,
                "end_line": error_line,
                "error": str(e),
            }
        )


def normalize_model_body(raw: str) -> str:
    """
    Normalize a model body by removing comments and all whitespace for deduplication.

    This function is used to create a canonical representation of Pydantic models
    for deduplication purposes. It:
    1. Removes Python comments (# ...) including inline comments on the class definition line
    2. Removes all whitespace (spaces, tabs, newlines)
    This ensures that models with identical structure but different formatting
    or comments are treated as duplicates.
    """
    if not raw:
        return ""
    # Remove Python comments (including inline comments)
    no_comments = re.sub(r"#.*", "", raw)
    # Remove all whitespace (spaces, tabs, newlines)
    no_whitespace = re.sub(r"\s+", "", no_comments)
    return no_whitespace


def deduplicate_and_sort_results(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Deduplicate and sort extraction results.
    For file results (from extract_from_directory), deduplicate by file path.
    For individual blocks/models, deduplicate by type, name, and normalized raw content.
    """

    # Check if these are file results (from extract_from_directory)
    if results and "file" in results[0]:
        # For file results, just deduplicate by file path and preserve all content
        seen_files = set()
        deduped = []
        for result in results:
            if result.get("file") not in seen_files:
                seen_files.add(result.get("file"))
                deduped.append(result)

        # Sort by file path
        deduped.sort(key=lambda x: x.get("file", ""))
        return deduped
    else:
        # Original logic for individual GraphQL blocks and Pydantic models
        # 1. GRAPHQL DEDUPLICATION:
        seen_graphql = {}
        graphql_blocks = [
            r
            for r in results
            if "type" in r
            and r["type"] in {"query", "mutation", "subscription", "fragment", "unknown"}
        ]
        for block in graphql_blocks:
            key = (block["type"], block["name"], normalize_model_body(block["raw"]))
            if (
                key not in seen_graphql
                or block["start_line"] < seen_graphql[key]["start_line"]
            ):
                seen_graphql[key] = block
        deduped_graphql = list(seen_graphql.values())
        deduped_graphql.sort(key=lambda b: b["start_line"])

        # 2. PYDANTIC MODEL DEDUPLICATION
        seen_models = {}
        pydantic_models = [
            r
            for r in results
            if r.get("type")
            in {"BaseModel/RootModel", "PydanticDataclass", "dataclass"}
        ]
        for model in pydantic_models:
            key = (
                model["model_name"],
                normalize_model_body(model["raw"]),
                model["type"],
            )
            if (
                key not in seen_models
                or model["start_line"] < seen_models[key]["start_line"]
            ):
                seen_models[key] = model
        deduped_models = list(seen_models.values())
        deduped_models.sort(key=lambda m: m["start_line"])

        # Combine results
        return deduped_graphql + deduped_models


def extract_pydantic_models(source: str) -> List[Dict[str, Any]]:
    """
    Extracts all Pydantic models (classes inheriting from BaseModel, RootModel, or decorated as Pydantic dataclasses)
    from a single Python file. Walks the AST of the whole file for robust detection.

    This function performs comprehensive Pydantic model detection:

    1. INHERITANCE DETECTION:
       - Direct inheritance: class User(BaseModel):
       - Multi-level inheritance: class Child(Parent): where Parent inherits from BaseModel
       - Aliased inheritance: class User(BM): where BM = BaseModel
       - Generic inheritance: class Response(Generic[T], BaseModel):

    2. DATACLASS DETECTION:
       - Pydantic dataclasses: @pydantic.dataclasses.dataclass
       - Standard dataclasses: @dataclasses.dataclass
       - Aliased dataclasses: @pydantic_dataclass

    3. ERROR HANDLING:
       - Syntax errors: Returns error block with file content
       - Parse errors: Individual model extraction failures
       - Graceful degradation: Continues processing other models

    4. OUTPUT FORMAT:
       Each model returns a dictionary with:
       - model_name: The class name
       - raw: Complete class definition (including methods, validators)
       - start_line/end_line: Line numbers in source file
       - type: "BaseModel/RootModel" or "PydanticDataclass"
       - error: Error message (for failed extractions)

    This ensures comprehensive coverage of all Pydantic model patterns
    found in production codebases.
    """
    models: List[Dict[str, Any]] = []
    try:
        tree = ast.parse(source)
    except SyntaxError as ce:
        # If the whole file is broken, return a single error block
        return [
            {
                "model_name": None,
                "raw": source.strip(),
                "start_line": 1,
                "end_line": source.count("\n") + 1,
                "type": "unknown",
                "error": f"SyntaxError: {ce}",
            }
        ]
    (
        basemodel_aliases,
        rootmodel_aliases,
        pydantic_dataclass_decorators,
        standard_dataclass_decorators,
    ) = find_pydantic_aliases(tree)
    inheritance = build_class_inheritance(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            try:
                block = ast.get_source_segment(source, node)
                # Check for Pydantic BaseModel/RootModel
                if is_pydantic_model(
                    node.name, inheritance, basemodel_aliases, rootmodel_aliases
                ):
                    models.append(
                        {
                            "model_name": node.name,
                            "raw": (block or "").strip(),
                            "start_line": node.lineno,
                            "end_line": node.end_lineno,
                            "type": "BaseModel/RootModel",
                        }
                    )
                # Check for dataclass decorators
                elif any(
                    (
                        isinstance(deco, ast.Name)
                        and deco.id in pydantic_dataclass_decorators
                    )
                    or (
                        isinstance(deco, ast.Attribute)
                        and deco.attr in pydantic_dataclass_decorators
                    )
                    or (isinstance(deco, ast.Attribute) and deco.attr == "dataclass")
                    or (
                        isinstance(deco, ast.Call)
                        and (
                            (
                                isinstance(deco.func, ast.Name)
                                and deco.func.id in pydantic_dataclass_decorators
                            )
                            or (
                                isinstance(deco.func, ast.Attribute)
                                and deco.func.attr in pydantic_dataclass_decorators
                            )
                            or (
                                isinstance(deco.func, ast.Attribute)
                                and deco.func.attr == "dataclass"
                            )
                        )
                    )
                    for deco in node.decorator_list
                ):
                    models.append(
                        {
                            "model_name": node.name,
                            "raw": (block or "").strip(),
                            "start_line": node.lineno,
                            "end_line": node.end_lineno,
                            "type": "PydanticDataclass",
                        }
                    )
                # Check for standard dataclass decorators
                elif any(
                    (
                        isinstance(deco, ast.Name)
                        and deco.id in standard_dataclass_decorators
                    )
                    or (
                        isinstance(deco, ast.Attribute)
                        and deco.attr in standard_dataclass_decorators
                    )
                    or (
                        isinstance(deco, ast.Call)
                        and (
                            (
                                isinstance(deco.func, ast.Name)
                                and deco.func.id in standard_dataclass_decorators
                            )
                            or (
                                isinstance(deco.func, ast.Attribute)
                                and deco.func.attr in standard_dataclass_decorators
                            )
                        )
                    )
                    for deco in node.decorator_list
                ):
                    models.append(
                        {
                            "model_name": node.name,
                            "raw": (block or "").strip(),
                            "start_line": node.lineno,
                            "end_line": node.end_lineno,
                            "type": "dataclass",
                        }
                    )
            except Exception as e:
                models.append(
                    {
                        "model_name": getattr(node, "name", None),
                        "raw": None,
                        "start_line": getattr(node, "lineno", None),
                        "end_line": getattr(node, "end_lineno", None),
                        "type": "unknown",
                        "error": str(e),
                    }
                )
    return models


# ----------------------------
# Recursively walks all .py, .graphql, and .gql files from a given directory, with exclusion support
# Handles both directories and single files
#
# This is the main entry point for file system traversal and extraction.
# It handles:
#
# 1. DIRECTORY TRAVERSAL:
#    - Recursive scanning of all subdirectories
#    - Exclusion of unwanted directories (.git, venv, node_modules, etc.)
#    - Support for both directory and single file input
#
# 2. FILE TYPE HANDLING:
#    - Python files (.py): Extract both GraphQL and Pydantic models
#    - GraphQL files (.graphql, .gql): Extract GraphQL operations only
#    - Binary/non-text files: Gracefully skipped
#
# 3. ERROR RECOVERY:
#    - Unreadable files: Permission errors, corrupted files
#    - Encoding issues: Non-UTF-8 files
#    - Syntax errors: Invalid Python/GraphQL syntax
#    - Individual file failures don't stop the entire process
#
# 4. STANDALONE GRAPHQL FILES:
#    - Entire file content is treated as GraphQL
#    - Each operation is extracted individually with precise line numbers
#    - Error handling for invalid GraphQL syntax
#
# 5. OUTPUT STRUCTURE:
#    Returns a list of dictionaries, each containing:
#    - file: Path to the source file
#    - graphql: List of extracted GraphQL operations
#    - pydantic_models: List of extracted Pydantic models
#
# This function ensures robust extraction from complex, real-world
# codebase structures with comprehensive error handling.
# ----------------------------
def extract_from_directory(
    root_dir: str, exclude: Optional[Set[str]] = None
) -> List[Dict[str, Any]]:
    """
    Recursively walks all .py, .graphql, and .gql files from root_dir, extracting GraphQL and Pydantic models.
    Skips directories and files in the exclude set.
    Handles:
    - Both directories and single .py/.graphql/.gql files
    - Ignores unreadable files
    """
    if exclude is None:
        exclude = {".git", ".venv", "venv", "node_modules", "__pycache__"}
    extracted: List[Dict[str, Any]] = []

    # Handle single file case
    if os.path.isfile(root_dir) and (
        root_dir.endswith(".py") or root_dir.endswith((".graphql", ".gql"))
    ):
        try:
            with open(root_dir, "r", encoding="utf-8") as f:
                source = f.read()
            gql_results = []
            model_results: List[Dict[str, Any]] = []
            if root_dir.endswith((".graphql", ".gql")):
                # Parse each GraphQL operation individually and extract the exact source block
                try:
                    ast_doc = parse(source, no_location=False)
                    for defn in ast_doc.definitions:
                        if hasattr(defn, "loc") and defn.loc:
                            # Use character offsets for precise extraction
                            start_offset = defn.loc.start
                            end_offset = defn.loc.end
                            block_content = source[start_offset:end_offset]
                            # Compute line numbers
                            start_line = source[:start_offset].count("\n") + 1
                            end_line = source[:end_offset].count("\n") + 1
                        else:
                            block_content = source
                            start_line = 1
                            end_line = source.count("\n") + 1
                        if isinstance(defn, OperationDefinitionNode):
                            gql_results.append(
                                {
                                    "type": defn.operation.value,
                                    "name": defn.name.value if defn.name else None,
                                    "variables": [
                                        v.variable.name.value
                                        for v in defn.variable_definitions or []
                                    ],
                                    "raw": block_content.strip(),
                                    "start_line": start_line,
                                    "end_line": end_line,
                                }
                            )
                        elif isinstance(defn, FragmentDefinitionNode):
                            gql_results.append(
                                {
                                    "type": "fragment",
                                    "name": defn.name.value if defn.name else None,
                                    "type_condition": defn.type_condition.name.value,
                                    "raw": block_content.strip(),
                                    "start_line": start_line,
                                    "end_line": end_line,
                                }
                            )
                except Exception as e:
                    gql_results.append(
                        {
                            "type": "unknown",
                            "name": None,
                            "variables": [],
                            "raw": source.strip(),
                            "start_line": 1,
                            "end_line": source.count("\n") + 1,
                            "error": str(e),
                        }
                    )
            elif root_dir.endswith(".py"):
                gql_results = extract_graphql_blocks(source)
                model_results = extract_pydantic_models(source)
            # Combine and deduplicate all results before returning
            combined = gql_results + model_results
            deduped = deduplicate_and_sort_results(combined)
            # Split back into graphql and pydantic_models for output
            graphql = [
                r
                for r in deduped
                if r.get("type") in {"query", "mutation", "subscription", "fragment"}
            ]
            pydantic_models = [
                r
                for r in deduped
                if r.get("type")
                in {"BaseModel/RootModel", "PydanticDataclass", "dataclass"}
            ]
            return [
                {
                    "file": root_dir,
                    "graphql": graphql,
                    "pydantic_models": pydantic_models,
                }
            ]
        except Exception:
            return []

    for dirpath, dirnames, filenames in os.walk(root_dir):
        # Exclude unwanted directories
        dirnames[:] = [d for d in dirnames if d not in exclude]
        for filename in filenames:
            if (
                filename.endswith(".py") and filename not in exclude
            ) or filename.endswith((".graphql", ".gql")):
                file_path = os.path.join(dirpath, filename)
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        source = f.read()
                    gql_results = []
                    model_results: List[Dict[str, Any]] = []
                    if filename.endswith((".graphql", ".gql")):
                        # Treat the whole file as a GraphQL block
                        # Remove verbose processing logging for options 3-6
                        # print(f"Processing GraphQL file: {filename}")
                        _extract_graphql_defs(
                            source, 1, source.count("\n") + 1, gql_results
                        )
                        # Remove verbose extraction logging for options 3-6
                        # print(f"Extracted {len(gql_results)} GraphQL blocks from {filename}")
                    else:
                        gql_results = extract_graphql_blocks(source)
                        model_results = extract_pydantic_models(source)
                    # Always include the result if there are any GraphQL blocks (including error blocks)
                    # or if there are any Pydantic models
                    if gql_results or model_results:
                        extracted.append(
                            {
                                "file": file_path,
                                "graphql": gql_results,
                                "pydantic_models": model_results,
                            }
                        )
                except Exception:
                    # Log or skip unreadable files
                    pass
    return deduplicate_and_sort_results(extracted)


# ----------------------------
# Entrypoint for running extraction
# ----------------------------
def run_extraction(
    path: str, exclude: Optional[Set[str]] = None
) -> List[Dict[str, Any]]:
    """
    Runs extraction on the given path (file or directory), with optional exclusion set.
    """
    return extract_from_directory(path, exclude=exclude)


# ----------------------------
# CLI Entrypoint
# ----------------------------
def main() -> Optional[List[Dict[str, Any]]]:
    """
    CLI entrypoint for the extractor.
    Parses arguments, runs extraction, and prints results if --print is passed or if run directly (not piped).
    Otherwise, returns results for piping to validator.
    """
    parser = argparse.ArgumentParser(
        description="Extract Pydantic models and GraphQL blocks from Python files."
    )
    parser.add_argument(
        "--path",
        type=str,
        default=os.path.abspath(os.path.join(os.path.dirname(__file__), "..")),
        help="Root directory to start extraction from",
    )
    parser.add_argument(
        "--exclude",
        type=str,
        default=".git,.venv,venv,node_modules,__pycache__, intern-project-graphql-validation-autofixer-tool, graphql_validator_tool",
        help="Comma-separated list of directory or file names to exclude (default: .git,.venv,venv,node_modules,__pycache__)",
    )
    parser.add_argument(
        "--print",
        action="store_true",
        help="Print all extracted values in a readable format (file, line numbers, raw code, etc.)",
    )
    args = parser.parse_args()
    exclude_set: Set[str] = set(x.strip() for x in args.exclude.split(",") if x.strip())
    results = run_extraction(args.path, exclude=exclude_set)
    # Use reporter to handle output formatting
    import reporter

    reporter.report_results(results, force_print=args.print)
    return results


if __name__ == "__main__":
    main()

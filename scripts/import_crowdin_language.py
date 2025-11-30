"""
Import translations from Crowdin JSON export and merge them into language module files.

Usage:
    python scripts/import_crowdin_language.py path/to/EN_US.json
    python scripts/import_crowdin_language.py path/to/ZH_TW.json --dry-run

The script will:
1. Parse the Crowdin JSON file (array of {identifier, translation, ...})
2. Extract the language code from the filename (e.g., EN_US from EN_US.json)
3. Scan module files to find actual variable names defined in each file
4. Update each module file in app/Language/modules/ with the new language entries
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

# Ensure project root is on path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

LANGUAGE_MODULES_DIR = ROOT_DIR / "app" / "Language" / "modules"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import Crowdin translations into language module files."
    )
    parser.add_argument(
        "crowdin_file",
        type=Path,
        help="Path to the Crowdin JSON export file (e.g., EN_US.json)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be changed without modifying files",
    )
    return parser.parse_args()


def load_crowdin_json(path: Path) -> list[dict[str, Any]]:
    """Load the Crowdin export JSON file."""
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def extract_language_code(filename: str) -> str:
    """Extract language code from filename (e.g., 'EN_US' from 'EN_US.json')."""
    return Path(filename).stem.upper()


def scan_module_files() -> dict[str, tuple[Path, str]]:
    """
    Scan all module files and extract variable names that define language dicts.

    Returns a dict: {variable_name: (file_path, variable_name)}
    e.g., {"set_prize_name": (Path(".../lottery_list.py"), "set_prize_name")}
    """
    var_to_file: dict[str, tuple[Path, str]] = {}

    # Pattern to match variable assignments like: variable_name = {
    var_pattern = re.compile(r"^([a-z_][a-z0-9_]*)\s*=\s*\{", re.MULTILINE)

    for py_file in LANGUAGE_MODULES_DIR.glob("*.py"):
        if py_file.name == "__init__.py":
            continue

        try:
            content = py_file.read_text(encoding="utf-8")
            for match in var_pattern.finditer(content):
                var_name = match.group(1)
                # Check if this looks like a language dict (contains "ZH_CN")
                # Find the dict content
                start = match.end() - 1
                if '"ZH_CN"' in content[start : start + 500]:
                    var_to_file[var_name] = (py_file, var_name)
        except Exception as e:
            print(f"  Warning: Error reading {py_file}: {e}")

    return var_to_file


def group_by_module(entries: list[dict[str, Any]]) -> dict[str, dict[str, str]]:
    """
    Group Crowdin entries by module name.

    Returns a dict: {module_name: {dotted_key: translation}}
    e.g., {"basic_settings": {"title.name": "Basic settings", ...}}
    """
    modules: dict[str, dict[str, str]] = {}

    for entry in entries:
        identifier = entry.get("identifier", "")
        translation = entry.get("translation", "")

        if not identifier or not translation:
            continue

        # Split identifier: "basic_settings.title.name" -> ["basic_settings", "title", "name"]
        parts = identifier.split(".")
        if len(parts) < 2:
            continue

        module_name = parts[0]
        # The rest is the key path within the module
        key_path = ".".join(parts[1:])

        if module_name not in modules:
            modules[module_name] = {}
        modules[module_name][key_path] = translation

    return modules


def set_nested_value(d: dict, key_path: str, value: Any) -> None:
    """
    Set a nested value in a dictionary using dot notation.

    e.g., set_nested_value(d, "title.name", "Hello")
    sets d["title"]["name"] = "Hello"
    """
    keys = key_path.split(".")
    current = d

    for key in keys[:-1]:
        if key not in current:
            current[key] = {}
        elif not isinstance(current[key], dict):
            # If current value is not a dict, we need to convert it
            current[key] = {}
        current = current[key]

    # Set the final value
    final_key = keys[-1]
    current[final_key] = value


def build_language_dict(translations: dict[str, str]) -> dict[str, Any]:
    """
    Build a nested dictionary from flat dotted keys.

    Input: {"title.name": "Hello", "title.description": "World"}
    Output: {"title": {"name": "Hello", "description": "World"}}
    """
    result: dict[str, Any] = {}
    for key_path, value in translations.items():
        set_nested_value(result, key_path, value)
    return result


def format_dict_as_python(d: dict, indent: int = 0) -> str:
    """Format a dictionary as Python code with proper indentation."""
    lines = []
    prefix = "    " * indent
    inner_prefix = "    " * (indent + 1)

    lines.append("{")
    items = list(d.items())

    for i, (key, value) in enumerate(items):
        comma = "," if i < len(items) - 1 else ","

        if isinstance(value, dict):
            nested = format_dict_as_python(value, indent + 1)
            lines.append(f'{inner_prefix}"{key}": {nested}{comma}')
        elif isinstance(value, str):
            # Escape backslashes, quotes, and newlines in strings
            escaped = (
                value.replace("\\", "\\\\")
                .replace('"', '\\"')
                .replace("\n", "\\n")
                .replace("\r", "\\r")
                .replace("\t", "\\t")
            )
            lines.append(f'{inner_prefix}"{key}": "{escaped}"{comma}')
        elif isinstance(value, list):
            list_str = json.dumps(value, ensure_ascii=False)
            lines.append(f'{inner_prefix}"{key}": {list_str}{comma}')
        else:
            lines.append(f'{inner_prefix}"{key}": {repr(value)}{comma}')

    lines.append(f"{prefix}}}")
    return "\n".join(lines)


def update_module_file(
    module_path: Path,
    var_name: str,
    language_code: str,
    translations: dict[str, str],
    dry_run: bool = False,
) -> bool:
    """
    Update a language module file to include the new language.

    Returns True if the file was modified (or would be in dry-run mode).
    """
    if not module_path.exists():
        print(f"  Warning: Module file not found: {module_path}")
        return False

    content = module_path.read_text(encoding="utf-8")

    # Build the nested dictionary for this language
    lang_dict = build_language_dict(translations)

    # Check if language already exists in the module
    # Pattern to find the variable dict definition
    # e.g., "basic_settings = {"
    dict_pattern = rf"^{re.escape(var_name)}\s*=\s*\{{"
    match = re.search(dict_pattern, content, re.MULTILINE)

    if not match:
        print(f"  Warning: Could not find '{var_name} = {{' in {module_path.name}")
        return False

    # Check if language code already exists
    lang_pattern = rf'"{language_code}":\s*\{{'
    if re.search(lang_pattern, content):
        print(
            f"  Language '{language_code}' already exists in {module_path.name}:{var_name}, skipping..."
        )
        # For now, we'll skip updating existing entries to avoid complexity
        # A more sophisticated approach would parse and merge
        # For safety, let's just add if not exists
        return False

    # Find the position to insert the new language
    # We'll insert after "ZH_CN": {...}, if it exists
    # Strategy: Find the closing of the main dict and insert before it

    # Parse the file to find where to insert
    # Simple approach: find the last "}" that closes the module dict

    # Find all language entries and their positions
    # Pattern: "LANG_CODE": {
    lang_entries = list(re.finditer(r'"([A-Z_]+)":\s*\{', content))

    if not lang_entries:
        print(f"  Warning: No language entries found in {module_path.name}")
        return False

    # Find the end of the last language entry
    # This is tricky due to nested braces, so we'll use a different approach:
    # Insert the new language entry at the end of the dict, before the final }

    # Find the module dict definition start
    dict_start = match.end() - 1  # Position of the opening {

    # Count braces to find the matching closing brace
    brace_count = 0
    dict_end = -1
    in_string = False
    escape_next = False

    for i, char in enumerate(content[dict_start:], start=dict_start):
        if escape_next:
            escape_next = False
            continue
        if char == "\\":
            escape_next = True
            continue
        if char == '"' and not escape_next:
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == "{":
            brace_count += 1
        elif char == "}":
            brace_count -= 1
            if brace_count == 0:
                dict_end = i
                break

    if dict_end == -1:
        print(
            f"  Warning: Could not find closing brace for {var_name} in {module_path.name}"
        )
        return False

    # Format the new language entry
    formatted_dict = format_dict_as_python(lang_dict, indent=1)
    new_entry = f'    "{language_code}": {formatted_dict},\n'

    # Check if there's a trailing comma before the closing brace
    # Look backwards from dict_end to find the last non-whitespace character
    before_close = content[dict_start:dict_end]
    last_non_ws_idx = len(before_close) - 1
    while last_non_ws_idx >= 0 and before_close[last_non_ws_idx] in " \t\n\r":
        last_non_ws_idx -= 1

    # If the last non-whitespace character is not a comma, we need to add one
    if last_non_ws_idx >= 0 and before_close[last_non_ws_idx] != ",":
        # Insert a comma after the last non-whitespace character
        insert_comma_pos = dict_start + last_non_ws_idx + 1
        content = content[:insert_comma_pos] + "," + content[insert_comma_pos:]
        # Adjust dict_end since we added a character
        dict_end += 1

    # Insert the new language at the end, before the closing brace
    new_content = content[:dict_end] + new_entry + content[dict_end:]

    if dry_run:
        print(f"  Would add '{language_code}' to {module_path.name}:{var_name}")
        print(
            f"    Keys: {list(translations.keys())[:5]}{'...' if len(translations) > 5 else ''}"
        )
        return True

    module_path.write_text(new_content, encoding="utf-8")
    print(f"  Added '{language_code}' to {module_path.name}:{var_name}")
    return True


def main() -> None:
    args = parse_args()

    crowdin_file: Path = args.crowdin_file
    if not crowdin_file.exists():
        print(f"Error: File not found: {crowdin_file}")
        sys.exit(1)

    # Extract language code from filename
    language_code = extract_language_code(crowdin_file.name)
    print(f"Importing language: {language_code}")
    print(f"Source file: {crowdin_file}")
    print(f"Target directory: {LANGUAGE_MODULES_DIR}")
    print()

    # Scan module files to find actual variable names
    print("Scanning module files...")
    var_to_file = scan_module_files()
    print(
        f"Found {len(var_to_file)} language variables: {', '.join(sorted(var_to_file.keys()))}"
    )
    print()

    # Load Crowdin data
    entries = load_crowdin_json(crowdin_file)
    print(f"Loaded {len(entries)} translation entries")

    # Group by module (identifier prefix)
    modules = group_by_module(entries)
    print(f"Found {len(modules)} identifier prefixes in Crowdin file")
    print()

    # Match Crowdin modules to actual variable names
    updated_count = 0
    unmatched_modules = []

    for module_name, translations in sorted(modules.items()):
        # First, try to find by exact variable name match
        if module_name in var_to_file:
            file_path, var_name = var_to_file[module_name]
            if update_module_file(
                file_path, var_name, language_code, translations, args.dry_run
            ):
                updated_count += 1
        else:
            # Module not found in any file
            unmatched_modules.append(module_name)

    print()
    if unmatched_modules:
        print(
            f"Unmatched Crowdin modules ({len(unmatched_modules)}): {', '.join(sorted(unmatched_modules))}"
        )
        print("  (These identifiers have no matching variable in module files)")

    print()
    if args.dry_run:
        print(f"Dry run complete. Would update {updated_count} language entries.")
    else:
        print(f"Import complete. Updated {updated_count} language entries.")


if __name__ == "__main__":
    main()

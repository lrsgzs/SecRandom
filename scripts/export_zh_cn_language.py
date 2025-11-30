"""Export the ZH_CN language dictionary to a JSON file for external use."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT_DIR))

from app.tools.language_manager import get_simple_language_manager


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Dump the ZH_CN language bundle to a JSON file."
    )
    parser.add_argument(
        "-o",
        "--output",
        help="Destination file for the exported JSON. Defaults to scripts/zh_cn_language.json",
        type=Path,
        default=None,
    )
    return parser.parse_args()


def export_language(language_code: str, destination: Path) -> None:
    manager = get_simple_language_manager()
    languages = manager.get_all_languages()
    language_data = languages.get(language_code)

    if language_data is None:
        raise RuntimeError(
            f"Language {language_code} not found; available: {sorted(languages)}"
        )

    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8") as handle:
        json.dump(language_data, handle, ensure_ascii=False, indent=2)


def main() -> None:
    args = parse_args()
    default_path = Path(__file__).resolve().parent / "zh_cn_language.json"
    target_path = args.output or default_path

    print(f"Exporting ZH_CN resources to {target_path}")
    export_language("ZH_CN", target_path)
    print("Export complete.")


if __name__ == "__main__":
    main()

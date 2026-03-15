from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from release_notes import load_manifests, render_release_notes


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate release notes from release manifests.")
    parser.add_argument("--root", default=str(ROOT / "dist" / "release"), help="Root directory that contains release manifests.")
    parser.add_argument("--output", default="", help="Optional markdown output file.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifests = load_manifests(Path(args.root).resolve())
    notes = render_release_notes(manifests)
    if args.output:
        output_path = Path(args.output).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(notes, encoding="utf-8")
    else:
        print(notes, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

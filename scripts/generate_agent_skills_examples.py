from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nova.agents.skill_examples import generate_examples, inspect_skills


DEFAULT_SKILLS_ROOT = ROOT / "agent-skills-main" / "skills"
DEFAULT_OUTPUT_DIR = ROOT / "examples"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate standalone NovaScript agent examples from agent-skills-main.")
    parser.add_argument("--skills-root", default=str(DEFAULT_SKILLS_ROOT))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--include-nonportable", action="store_true", help="Also generate skills that depend on external vendor-specific workflows.")
    args = parser.parse_args()

    skills_root = Path(args.skills_root).resolve()
    output_dir = Path(args.output_dir).resolve()
    inventory = inspect_skills(skills_root)
    manifest = generate_examples(skills_root, output_dir, include_nonportable=args.include_nonportable)
    payload = {
        "skills_root": str(skills_root),
        "output_dir": str(output_dir),
        "generated": manifest,
        "skipped": inventory["skipped"] if not args.include_nonportable else {},
        "count": len(manifest),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

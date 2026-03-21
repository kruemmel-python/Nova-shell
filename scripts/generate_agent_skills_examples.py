from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nova.agents.skill_examples import generate_examples


DEFAULT_SKILLS_ROOT = ROOT / "agent-skills-main" / "skills"
DEFAULT_OUTPUT_DIR = ROOT / "examples"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate standalone NovaScript agent examples from agent-skills-main.")
    parser.add_argument("--skills-root", default=str(DEFAULT_SKILLS_ROOT))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    args = parser.parse_args()

    manifest = generate_examples(Path(args.skills_root).resolve(), Path(args.output_dir).resolve())
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

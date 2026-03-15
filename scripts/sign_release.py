from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from release_signing import (
    find_artifacts_for_gpg,
    gpg_detach_sign,
    require_gpg,
    verify_gpg_signature,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create detached GPG signatures for release artifacts.")
    parser.add_argument("--root", default=str(ROOT / "dist" / "release"), help="Directory containing release artifacts.")
    parser.add_argument("--gpg-homedir", default="", help="Optional GNUPGHOME used for signing and verification.")
    parser.add_argument("--gpg-passphrase", default="", help="Optional passphrase used with loopback pinentry for non-interactive signing.")
    parser.add_argument("--verify", action="store_true", help="Verify created signatures after signing.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.root).resolve()
    gpg = require_gpg()
    homedir = args.gpg_homedir or None
    passphrase = args.gpg_passphrase or None

    artifacts = find_artifacts_for_gpg(root)
    if not artifacts:
        raise SystemExit(f"no artifacts found under {root}")

    for artifact in artifacts:
        signature = gpg_detach_sign(artifact, gpg=gpg, homedir=homedir, passphrase=passphrase)
        if args.verify:
            verify_gpg_signature(signature, artifact, gpg=gpg, homedir=homedir)
        print(signature)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "build_release.py"
SPEC = importlib.util.spec_from_file_location("build_release_module", SCRIPT_PATH)
build_release = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = build_release
SPEC.loader.exec_module(build_release)


class BuildReleaseTests(unittest.TestCase):
    def test_default_source_date_epoch_reads_environment(self) -> None:
        with patch.dict(os.environ, {"SOURCE_DATE_EPOCH": "1700000000"}):
            self.assertEqual(build_release.default_source_date_epoch(), 1700000000)

    def test_default_source_date_epoch_rejects_invalid_environment(self) -> None:
        with patch.dict(os.environ, {"SOURCE_DATE_EPOCH": "invalid"}):
            with self.assertRaises(SystemExit):
                build_release.default_source_date_epoch()

    def test_write_subject_checksums_writes_expected_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = build_release.write_subject_checksums(
                root,
                "core",
                [
                    build_release.ArtifactRecord(kind="python", path="dist/release/nova-shell.whl", size=10, sha256="abc"),
                    build_release.ArtifactRecord(kind="installer", path="dist/release/nova-shell.msi", size=20, sha256="def"),
                ],
            )
            lines = output.read_text(encoding="utf-8").splitlines()

        self.assertEqual(output.name, f"nova-shell-{build_release.__version__}-core-subjects.checksums.txt")
        self.assertEqual(
            lines,
            [
                "abc  dist/release/nova-shell.whl",
                "def  dist/release/nova-shell.msi",
            ],
        )


if __name__ == "__main__":
    unittest.main()

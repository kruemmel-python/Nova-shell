import json
import tempfile
import unittest
from pathlib import Path

from release_notes import load_manifests, render_release_notes
from release_signing import find_artifacts_for_gpg, find_artifacts_for_windows_signing, is_windows_signable


class ReleaseAutomationTests(unittest.TestCase):
    def test_is_windows_signable(self) -> None:
        self.assertTrue(is_windows_signable(Path("nova-shell.exe")))
        self.assertTrue(is_windows_signable(Path("nova-shell.msi")))
        self.assertFalse(is_windows_signable(Path("nova-shell.zip")))

    def test_find_artifacts_for_windows_signing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "app.exe").write_text("x", encoding="utf-8")
            (root / "lib.dll").write_text("x", encoding="utf-8")
            (root / "notes.txt").write_text("x", encoding="utf-8")
            found = find_artifacts_for_windows_signing(root)
        self.assertEqual([path.name for path in found], ["app.exe", "lib.dll"])

    def test_find_artifacts_for_gpg_skips_signature_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "artifact.zip").write_text("x", encoding="utf-8")
            (root / "artifact.zip.sig").write_text("sig", encoding="utf-8")
            (root / "artifact.zip.asc").write_text("sig", encoding="utf-8")
            found = find_artifacts_for_gpg(root)
        self.assertEqual([path.name for path in found], ["artifact.zip"])

    def test_render_release_notes_from_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = {
                "name": "nova-shell",
                "version": "0.8.0",
                "profile": "core",
                "platform": {"system": "Windows", "machine": "AMD64", "platform": "Windows-11"},
                "built_at_utc": "2026-03-07T00:00:00+00:00",
                "extras": [],
                "artifacts": [
                    {"kind": "installer", "path": "dist/release/windows/core/nova-shell.msi", "size": 2048, "sha256": "abc123"},
                ],
            }
            (root / "nova-shell-0.8.0-core-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            manifests = load_manifests(root)
            notes = render_release_notes(manifests)
        self.assertEqual(len(manifests), 1)
        self.assertIn("# nova-shell 0.8.0", notes)
        self.assertIn("dist/release/windows/core/nova-shell.msi", notes)


if __name__ == "__main__":
    unittest.main()

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "build_android.py"
SPEC = importlib.util.spec_from_file_location("build_android_module", SCRIPT_PATH)
build_android = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = build_android
SPEC.loader.exec_module(build_android)

BRIDGE_PATH = Path(__file__).resolve().parents[1] / "android" / "app" / "src" / "main" / "python" / "nova_mobile_bridge.py"
BRIDGE_SPEC = importlib.util.spec_from_file_location("nova_mobile_bridge_test_module", BRIDGE_PATH)
nova_mobile_bridge = importlib.util.module_from_spec(BRIDGE_SPEC)
assert BRIDGE_SPEC.loader is not None
sys.modules[BRIDGE_SPEC.name] = nova_mobile_bridge
BRIDGE_SPEC.loader.exec_module(nova_mobile_bridge)


class BuildAndroidTests(unittest.TestCase):
    def test_collect_android_runtime_files_include_core_entrypoints(self) -> None:
        files = build_android.collect_android_runtime_files()
        names = {path.name for path in files}
        self.assertIn("nova_shell.py", names)
        self.assertIn("novascript.py", names)
        self.assertIn("README.md", names)

    def test_version_to_android_code_uses_first_three_numeric_parts(self) -> None:
        self.assertEqual(build_android.version_to_android_code("0.8.30"), 830)
        self.assertEqual(build_android.version_to_android_code("1.2.3-beta.5"), 10203)

    def test_clean_runtime_dir_preserves_gitkeep(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            python_root = Path(tmp) / "python"
            python_root.mkdir(parents=True)
            (python_root / "nova").mkdir()
            (python_root / "nova_mobile_runtime").mkdir()
            (python_root / "__pycache__").mkdir()
            (python_root / "nova_shell.py").write_text("old", encoding="utf-8")
            (python_root / "nova_mobile_bridge.py").write_text("keep", encoding="utf-8")

            with (
                patch.object(build_android, "ANDROID_RUNTIME_DIRS", ["nova"]),
                patch.object(build_android, "ANDROID_RUNTIME_FILES", ["nova_shell.py"]),
            ):
                build_android.clean_runtime_dir(python_root)

            self.assertFalse((python_root / "nova").exists())
            self.assertFalse((python_root / "nova_mobile_runtime").exists())
            self.assertFalse((python_root / "__pycache__").exists())
            self.assertFalse((python_root / "nova_shell.py").exists())
            self.assertTrue((python_root / "nova_mobile_bridge.py").is_file())

    def test_stage_android_runtime_copies_selected_tree_and_writes_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            python_root = Path(tmp) / "android" / "app" / "src" / "main" / "python"
            (root / "nova").mkdir(parents=True)
            (root / "nova" / "__init__.py").write_text("", encoding="utf-8")
            (root / "nova" / "__pycache__").mkdir()
            (root / "nova" / "__pycache__" / "ignored.pyc").write_bytes(b"pyc")
            (root / "examples").mkdir(parents=True)
            (root / "examples" / "demo.ns").write_text("flow demo {}\n", encoding="utf-8")
            (root / "examples" / ".nova").mkdir()
            (root / "examples" / ".nova" / "state.json").write_text("{}", encoding="utf-8")
            (root / "nova_shell.py").write_text('__version__ = "0.9.1"\n', encoding="utf-8")
            (root / "novascript.py").write_text("print('ok')\n", encoding="utf-8")

            with (
                patch.object(build_android, "ANDROID_RUNTIME_DIRS", ["nova", "examples"]),
                patch.object(build_android, "ANDROID_RUNTIME_FILES", ["nova_shell.py", "novascript.py"]),
            ):
                manifest_path = build_android.stage_android_runtime(root, python_root, clean=True)

            self.assertTrue((python_root / "nova" / "__init__.py").is_file())
            self.assertTrue((python_root / "examples" / "demo.ns").is_file())
            self.assertTrue((python_root / "nova_shell.py").is_file())
            self.assertFalse((python_root / "examples" / ".nova").exists())
            self.assertFalse((python_root / "nova" / "__pycache__").exists())

            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["version"], "0.9.1")
            self.assertEqual(payload["staged_directories"], ["nova", "examples"])
            self.assertEqual(payload["staged_files"], ["nova_shell.py", "novascript.py"])

    def test_resolve_gradle_command_falls_back_to_cached_wrapper_distribution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            executable_name = "gradle.bat" if build_android.os.name == "nt" else "gradle"
            preferred = home / ".gradle" / "wrapper" / "dists" / "gradle-8.14.2-bin" / "token" / "gradle-8.14.2" / "bin" / executable_name
            preferred.parent.mkdir(parents=True)
            preferred.write_text("@echo off\n", encoding="utf-8")
            newer_incompatible = home / ".gradle" / "wrapper" / "dists" / "gradle-9.2.0-bin" / "token" / "gradle-9.2.0" / "bin" / executable_name
            newer_incompatible.parent.mkdir(parents=True)
            newer_incompatible.write_text("@echo off\n", encoding="utf-8")

            with patch.object(build_android, "ANDROID_DIR", Path(tmp) / "missing-android"), patch.object(build_android, "ROOT", Path(tmp) / "missing-root"), patch.object(build_android, "shutil") as shutil_mock, patch.object(build_android.Path, "home", return_value=home):
                shutil_mock.which.return_value = None
                command = build_android.resolve_gradle_command()

            self.assertEqual(command, [str(preferred)])

    def test_resolve_apk_output_path_prefers_output_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            android_dir = Path(tmp) / "android"
            output_dir = android_dir / "app" / "build" / "outputs" / "apk" / "release"
            output_dir.mkdir(parents=True)
            (output_dir / "output-metadata.json").write_text(
                json.dumps(
                    {
                        "elements": [
                            {
                                "outputFile": "app-release-unsigned.apk",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            output_path = build_android.resolve_apk_output_path(android_dir, "release")
            self.assertEqual(output_path, output_dir / "app-release-unsigned.apk")

    def test_mobile_bridge_only_hard_blocks_local_compute_commands(self) -> None:
        self.assertIsNone(nova_mobile_bridge._blocked_command("remote http://10.0.2.2:8765 doctor"))
        self.assertIsNone(nova_mobile_bridge._blocked_command("mesh list"))
        self.assertIsNone(nova_mobile_bridge._blocked_command("pulse status"))
        self.assertEqual(nova_mobile_bridge._blocked_command("gpu kernel.cl"), "gpu")
        self.assertEqual(nova_mobile_bridge._blocked_command("cpp 1 + 1"), "cpp")

    def test_mobile_bridge_bootstrap_summary_reports_ready_for_staged_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime_root = Path(tmp)
            (runtime_root / "nova").mkdir()
            (runtime_root / "nova" / "__init__.py").write_text("", encoding="utf-8")
            (runtime_root / "nova_shell.py").write_text('__version__ = "0.8.30"\n', encoding="utf-8")
            (runtime_root / "android_runtime_manifest.json").write_text("{}", encoding="utf-8")

            with patch.object(nova_mobile_bridge, "_runtime_root", return_value=runtime_root):
                summary = nova_mobile_bridge.bootstrap_summary()

            self.assertTrue(summary["ok"])
            self.assertTrue(summary["runtime_ready"])
            self.assertEqual(summary["runtime_root"], str(runtime_root))

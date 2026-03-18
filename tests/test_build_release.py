import importlib.util
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
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

    def test_archive_bundle_uses_stable_relative_names_on_windows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle_dir = root / "standalone" / "nova_shell.dist"
            nested = bundle_dir / "toolchains" / "emsdk" / "upstream" / "emscripten"
            nested.mkdir(parents=True)
            payload = nested / "tool.py"
            payload.write_text("print('ok')\n", encoding="utf-8")

            with patch.object(build_release.os, "name", "nt"), patch.object(build_release.shutil, "which", return_value=None):
                archive_path = build_release.archive_bundle(bundle_dir, root / "nova-shell-test", source_date_epoch=None)

            self.assertEqual(archive_path.suffix, ".zip")
            with zipfile.ZipFile(archive_path, "r") as archive:
                self.assertIn(
                    "nova_shell.dist/toolchains/emsdk/upstream/emscripten/tool.py",
                    archive.namelist(),
                )

    def test_archive_bundle_prefers_external_tar_on_windows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle_dir = root / "standalone" / "nova_shell.dist"
            bundle_dir.mkdir(parents=True)
            (bundle_dir / "nova_shell.exe").write_text("binary", encoding="utf-8")
            created_archive = root / "nova-shell-test.zip"

            def fake_run(command: list[str], check: bool) -> SimpleNamespace:
                self.assertEqual(command[0], "tar.exe")
                self.assertIn("-a", command)
                self.assertEqual(command[-1], "nova_shell.dist")
                with zipfile.ZipFile(created_archive, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                    archive.write(bundle_dir / "nova_shell.exe", arcname="nova_shell.dist/nova_shell.exe")
                return SimpleNamespace(returncode=0)

            with (
                patch.object(build_release.os, "name", "nt"),
                patch.object(build_release.shutil, "which", side_effect=lambda name: "tar.exe" if name in {"tar.exe", "tar"} else None),
                patch.object(build_release.subprocess, "run", side_effect=fake_run) as run_mock,
            ):
                archive_path = build_release.archive_bundle(bundle_dir, root / "nova-shell-test", source_date_epoch=None)

            self.assertEqual(archive_path, created_archive)
            self.assertTrue(created_archive.is_file())
            run_mock.assert_called_once()

    def test_collect_nuitka_packages_for_enterprise_profile(self) -> None:
        with (
            patch.object(build_release.os, "name", "nt"),
            patch.object(build_release.sys, "platform", "win32"),
        ):
            self.assertEqual(
                build_release.collect_nuitka_packages("enterprise"),
                ["psutil", "unittest", "xml", "yaml"],
            )

    def test_collect_nuitka_modules_for_enterprise_profile(self) -> None:
        self.assertEqual(
            build_release.collect_nuitka_modules("enterprise"),
            ["ctypes.util", "ctypes.wintypes", "pdb", "pyarrow", "pyarrow.csv", "pyarrow.flight"],
        )

    def test_collect_nuitka_nofollow_for_enterprise_profile(self) -> None:
        with (
            patch.object(build_release.os, "name", "nt"),
            patch.object(build_release.sys, "platform", "win32"),
        ):
            self.assertEqual(
                build_release.collect_nuitka_nofollow("enterprise"),
                ["numpy", "pyarrow.tests", "pyarrow.vendored", "pyopencl", "torch", "wasmtime"],
            )

    def test_collect_nuitka_nofollow_for_windows_core_profile(self) -> None:
        with (
            patch.object(build_release.os, "name", "nt"),
            patch.object(build_release.sys, "platform", "win32"),
        ):
            self.assertEqual(
                build_release.collect_nuitka_nofollow("core"),
                ["numpy", "psutil", "pyarrow.tests", "pyarrow.vendored", "pyopencl", "torch", "wasmtime", "yaml"],
            )

    def test_collect_nuitka_compile_flags_for_windows_enterprise_profile(self) -> None:
        with (
            patch.object(build_release.os, "name", "nt"),
            patch.object(build_release.sys, "platform", "win32"),
        ):
            self.assertEqual(
                build_release.collect_nuitka_compile_flags("enterprise"),
                ["--low-memory", "--jobs=1", "--lto=no"],
            )

    def test_collect_sideload_packages_for_windows_enterprise_profile(self) -> None:
        with (
            patch.object(build_release.os, "name", "nt"),
            patch.object(build_release.sys, "platform", "win32"),
        ):
            self.assertEqual(build_release.collect_sideload_packages("enterprise"), ["wasmtime", "numpy", "torch", "pyopencl"])

    def test_collect_sideload_packages_for_windows_core_profile(self) -> None:
        with (
            patch.object(build_release.os, "name", "nt"),
            patch.object(build_release.sys, "platform", "win32"),
        ):
            self.assertEqual(build_release.collect_sideload_packages("core"), ["psutil", "yaml", "wasmtime", "numpy", "torch", "pyopencl"])

    def test_collect_sideload_packages_for_linux_enterprise_profile(self) -> None:
        with (
            patch.object(build_release.os, "name", "posix"),
            patch.object(build_release.sys, "platform", "linux"),
        ):
            self.assertEqual(build_release.collect_sideload_packages("enterprise"), ["wasmtime", "numpy", "torch"])

    def test_collect_nuitka_deployment_flags_for_windows_enterprise_profile(self) -> None:
        with (
            patch.object(build_release.os, "name", "nt"),
            patch.object(build_release.sys, "platform", "win32"),
        ):
            self.assertEqual(
                build_release.collect_nuitka_deployment_flags("enterprise"),
                ["self-execution", "excluded-module-usage"],
            )

    def test_stage_sideload_distribution_copies_record_files_without_top_level(self) -> None:
        class FakeDistribution:
            def __init__(self, path: Path, files: list[str]) -> None:
                self._path = path
                self.files = files

            def locate_file(self, path: str) -> Path:
                return self._path.parent / path

            def read_text(self, filename: str) -> str | None:
                if filename == "top_level.txt":
                    return None
                return None

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            site_packages = root / "site-packages"
            site_packages.mkdir()

            dist_info = site_packages / "example-1.0.dist-info"
            dist_info.mkdir()
            (dist_info / "METADATA").write_text("metadata", encoding="utf-8")

            package_dir = site_packages / "examplepkg"
            package_dir.mkdir()
            (package_dir / "__init__.py").write_text("__all__ = []\n", encoding="utf-8")

            libs_dir = site_packages / "examplepkg.libs"
            libs_dir.mkdir()
            (libs_dir / "runtime.dll").write_text("dll", encoding="utf-8")

            module_file = site_packages / "helper_mod.py"
            module_file.write_text("VALUE = 1\n", encoding="utf-8")

            distribution = FakeDistribution(
                dist_info,
                [
                    "example-1.0.dist-info/METADATA",
                    "examplepkg/__init__.py",
                    "examplepkg.libs/runtime.dll",
                    "helper_mod.py",
                ],
            )

            sideload_root = root / "vendor-py"
            sideload_root.mkdir()

            build_release.stage_sideload_distribution(distribution, sideload_root, copied=set())

            self.assertTrue((sideload_root / "example-1.0.dist-info" / "METADATA").exists())
            self.assertTrue((sideload_root / "examplepkg" / "__init__.py").exists())
            self.assertTrue((sideload_root / "examplepkg.libs" / "runtime.dll").exists())
            self.assertTrue((sideload_root / "helper_mod.py").exists())

    def test_stage_sideload_distribution_uses_top_level_copy_for_torch(self) -> None:
        class FakeDistribution:
            def __init__(self, path: Path) -> None:
                self._path = path
                self.files = []
                self.metadata = {"Name": "torch"}

            def locate_file(self, path: str) -> Path:
                return self._path.parent / path

            def read_text(self, filename: str) -> str | None:
                if filename == "top_level.txt":
                    return "functorch\ntorch\ntorchgen\n"
                return None

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            site_packages = root / "site-packages"
            site_packages.mkdir()

            dist_info = site_packages / "torch-1.0.dist-info"
            dist_info.mkdir()
            (dist_info / "METADATA").write_text("metadata", encoding="utf-8")

            for folder_name in ("functorch", "torch", "torchgen"):
                package_dir = site_packages / folder_name
                package_dir.mkdir()
                (package_dir / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")

            sideload_root = root / "vendor-py"
            sideload_root.mkdir()

            build_release.stage_sideload_distribution(FakeDistribution(dist_info), sideload_root, copied=set())

            self.assertTrue((sideload_root / "torch-1.0.dist-info" / "METADATA").exists())
            self.assertTrue((sideload_root / "functorch" / "__init__.py").exists())
            self.assertTrue((sideload_root / "torch" / "__init__.py").exists())
            self.assertTrue((sideload_root / "torchgen" / "__init__.py").exists())

    def test_safe_path_helpers_return_false_on_oserror(self) -> None:
        path = Path("Z:/definitely-not-real")

        with patch.object(Path, "exists", side_effect=OSError("stat failed")):
            self.assertFalse(build_release.safe_path_exists(path))

        with patch.object(Path, "is_dir", side_effect=OSError("stat failed")):
            self.assertFalse(build_release.safe_path_is_dir(path))

    def test_build_nuitka_command_includes_enterprise_packages_and_modules(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(build_release.os, "name", "nt"),
            patch.object(build_release.sys, "platform", "win32"),
        ):
            command = build_release.build_nuitka_command("enterprise", "python", Path(tmp))

        self.assertIn("--include-package=psutil", command)
        self.assertIn("--include-package=unittest", command)
        self.assertIn("--include-package=yaml", command)
        self.assertIn("--include-module=pyarrow", command)
        self.assertIn("--include-module=pyarrow.csv", command)
        self.assertIn("--include-module=pyarrow.flight", command)
        self.assertIn("--include-module=pdb", command)
        self.assertIn("--include-module=ctypes.util", command)
        self.assertIn("--include-module=ctypes.wintypes", command)
        self.assertIn("--nofollow-import-to=pyarrow.tests", command)
        self.assertIn("--nofollow-import-to=pyarrow.vendored", command)
        self.assertIn("--nofollow-import-to=numpy", command)
        self.assertIn("--nofollow-import-to=pyopencl", command)
        self.assertIn("--nofollow-import-to=wasmtime", command)
        self.assertIn("--low-memory", command)
        self.assertIn("--jobs=1", command)
        self.assertIn("--lto=no", command)
        self.assertNotIn("--include-package=wasmtime", command)
        self.assertNotIn("--include-package=numpy", command)
        self.assertNotIn("--include-package=pyopencl", command)
        self.assertNotIn("--include-package=torch", command)
        self.assertIn("--no-deployment-flag=self-execution", command)
        self.assertIn("--no-deployment-flag=excluded-module-usage", command)

    def test_stage_local_runtime_directories_copies_atheria_tree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_dir = root / "Atheria"
            source_dir.mkdir()
            (source_dir / "atheria_core.py").write_text("VALUE = 1\n", encoding="utf-8")
            (source_dir / "__pycache__").mkdir()
            (source_dir / "__pycache__" / "cache.pyc").write_bytes(b"cache")

            bundle_dir = root / "bundle"
            bundle_dir.mkdir()

            with patch.object(build_release, "collect_local_runtime_directories", return_value=[source_dir]):
                build_release.stage_local_runtime_directories(
                    bundle_dir,
                    build_context=build_release.BuildContext(
                        source_date_epoch=None,
                        timestamp_utc="2026-03-08T00:00:00+00:00",
                        env={},
                    ),
                )

            self.assertTrue((bundle_dir / "Atheria" / "atheria_core.py").exists())
            self.assertFalse((bundle_dir / "Atheria" / "__pycache__").exists())

    def test_stage_local_runtime_directories_copies_wiki_tree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_dir = root / "WIKI"
            source_dir.mkdir()
            (source_dir / "Home.md").write_text("# Home\n", encoding="utf-8")

            bundle_dir = root / "bundle"
            bundle_dir.mkdir()

            with patch.object(build_release, "collect_local_runtime_directories", return_value=[source_dir]):
                build_release.stage_local_runtime_directories(
                    bundle_dir,
                    build_context=build_release.BuildContext(
                        source_date_epoch=None,
                        timestamp_utc="2026-03-08T00:00:00+00:00",
                        env={},
                    ),
                )

            self.assertTrue((bundle_dir / "WIKI" / "Home.md").exists())

    def test_stage_bundled_emsdk_writes_wrapper_and_runtime_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache_root = root / "emsdk-cache"
            (cache_root / "upstream" / "emscripten").mkdir(parents=True)
            (cache_root / "upstream" / "bin").mkdir(parents=True)
            (cache_root / "python" / "3.12.0").mkdir(parents=True)
            (cache_root / "node" / "18.0.0_64bit" / "bin").mkdir(parents=True)
            (cache_root / "upstream" / "emscripten" / "emcc.py").write_text("print('emcc')\n", encoding="utf-8")
            (cache_root / "upstream" / "bin" / "clang.exe").write_text("clang", encoding="utf-8")
            (cache_root / "python" / "3.12.0" / "python.exe").write_text("python", encoding="utf-8")
            (cache_root / "node" / "18.0.0_64bit" / "bin" / "node.exe").write_text("node", encoding="utf-8")

            bundle_dir = root / "bundle"
            bundle_dir.mkdir()

            with (
                patch.object(build_release.os, "name", "nt"),
                patch.object(build_release.sys, "platform", "win32"),
                patch.object(build_release, "ensure_emsdk_cache", return_value=cache_root),
                patch.object(build_release, "stage_minimal_python_runtime", side_effect=lambda target: (target.mkdir(parents=True, exist_ok=True), (target / "python.exe").write_text("python", encoding="utf-8"))),
            ):
                build_release.stage_bundled_emsdk(
                    bundle_dir,
                    "core",
                    build_context=build_release.BuildContext(
                        source_date_epoch=None,
                        timestamp_utc="2026-03-15T00:00:00+00:00",
                        env={},
                    ),
                )
                build_release.write_runtime_config(bundle_dir, "core")

            wrapper = bundle_dir / build_release.BUNDLED_TOOLCHAIN_DIR / build_release.EMSDK_WRAPPER_NAME
            config = bundle_dir / build_release.BUNDLED_TOOLCHAIN_DIR / "emsdk" / ".emscripten"
            runtime_config = bundle_dir / build_release.RUNTIME_CONFIG_FILE

            self.assertTrue(wrapper.exists())
            self.assertTrue(config.exists())
            payload = runtime_config.read_text(encoding="utf-8")
            self.assertIn("toolchains", payload)
            self.assertIn(build_release.EMSDK_WRAPPER_NAME, payload)
            self.assertIn("EMSCRIPTEN_ROOT", config.read_text(encoding="utf-8"))
            self.assertIn("if not defined EM_CACHE", wrapper.read_text(encoding="utf-8"))

    def test_stage_emsdk_runtime_subset_avoids_robocopy_for_windows_copy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache_root = root / "emsdk-cache"
            (cache_root / "upstream" / "bin").mkdir(parents=True)
            (cache_root / "upstream" / "bin" / "clang.exe").write_text("clang", encoding="utf-8")
            target_root = root / "target"

            recorded_calls: list[dict[str, object]] = []

            def _record_copy(src: Path, dst: Path, *, ignore_patterns: tuple[str, ...] = (), prefer_robocopy: bool = True) -> None:
                recorded_calls.append(
                    {
                        "src": src,
                        "dst": dst,
                        "ignore_patterns": ignore_patterns,
                        "prefer_robocopy": prefer_robocopy,
                    }
                )
                dst.mkdir(parents=True, exist_ok=True)

            with (
                patch.object(build_release, "safe_copytree", side_effect=_record_copy),
                patch.object(build_release, "stage_minimal_python_runtime"),
                patch.object(build_release, "stage_minimal_node_runtime"),
            ):
                build_release.stage_emsdk_runtime_subset(cache_root, target_root)

            self.assertTrue(recorded_calls)
            self.assertTrue(all(call["prefer_robocopy"] is False for call in recorded_calls))

    def test_stage_local_runtime_directories_copies_runtime_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime_file = root / "trend_rss_sensor.py"
            runtime_file.write_text("VALUE = 1\n", encoding="utf-8")

            bundle_dir = root / "bundle"
            bundle_dir.mkdir()

            with (
                patch.object(build_release, "collect_local_runtime_directories", return_value=[]),
                patch.object(build_release, "collect_local_runtime_files", return_value=[runtime_file]),
            ):
                build_release.stage_local_runtime_directories(
                    bundle_dir,
                    build_context=build_release.BuildContext(
                        source_date_epoch=1700000000,
                        timestamp_utc="2026-03-08T00:00:00+00:00",
                        env={},
                    ),
                )

            target = bundle_dir / "trend_rss_sensor.py"
            self.assertTrue(target.exists())
            self.assertEqual(target.read_text(encoding="utf-8"), "VALUE = 1\n")

    def test_collect_local_runtime_files_includes_morning_briefing_script(self) -> None:
        files = build_release.collect_local_runtime_files()
        names = {path.name for path in files}
        self.assertIn("morning_briefing.ns", names)

    def test_prune_bundle_runtime_state_removes_nova_lens_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle_dir = Path(tmp)
            lens_dir = bundle_dir / ".nova_lens"
            lens_dir.mkdir()
            (lens_dir / "lineage.db").write_text("db", encoding="utf-8")
            keep_file = bundle_dir / "nova_shell.exe"
            keep_file.write_text("exe", encoding="utf-8")

            build_release.prune_bundle_runtime_state(bundle_dir)

            self.assertFalse(lens_dir.exists())
            self.assertTrue(keep_file.exists())

    def test_prune_bundle_runtime_state_removes_emsdk_cache_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle_dir = Path(tmp)
            cache_dir = bundle_dir / "toolchains" / "emsdk-cache"
            cache_dir.mkdir(parents=True)
            (cache_dir / "cache.db").write_text("cache", encoding="utf-8")

            build_release.prune_bundle_runtime_state(bundle_dir)

            self.assertFalse(cache_dir.exists())

    def test_stage_windows_installer_support_files_copies_upgrade_helper(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            installer_root = Path(tmp) / "installers"
            installer_root.mkdir()

            staged = build_release.stage_windows_installer_support_files(
                installer_root,
                build_context=build_release.BuildContext(
                    source_date_epoch=1700000000,
                    timestamp_utc="2024-01-01T00:00:00+00:00",
                    env={},
                ),
            )

            names = {path.name for path in staged}
            self.assertIn("upgrade_windows_install.ps1", names)
            self.assertIn("upgrade_windows_install.README.txt", names)
            self.assertTrue((installer_root / "upgrade_windows_install.ps1").exists())
            self.assertTrue((installer_root / "upgrade_windows_install.README.txt").exists())

    def test_safe_platform_helpers_avoid_windows_wmi_path(self) -> None:
        with (
            patch.object(build_release.os, "name", "nt"),
            patch.object(build_release.sys, "platform", "win32"),
            patch.dict(build_release.os.environ, {"PROCESSOR_ARCHITECTURE": "AMD64"}, clear=False),
            patch.object(build_release.platform, "system", side_effect=AssertionError("platform.system should not be used")),
            patch.object(build_release.platform, "machine", side_effect=AssertionError("platform.machine should not be used")),
            patch.object(build_release.platform, "platform", side_effect=AssertionError("platform.platform should not be used")),
            patch.object(build_release.sys, "getwindowsversion", return_value=SimpleNamespace(major=10, minor=0, build=29531)),
        ):
            self.assertEqual(build_release.safe_system_name(), "Windows")
            self.assertEqual(build_release.safe_machine_name(), "amd64")
            self.assertEqual(build_release.safe_platform_string(), "Windows-10.0.29531-amd64")


if __name__ == "__main__":
    unittest.main()

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nova_shell import __version__
from release_packaging import (
    format_deb_description,
    load_release_metadata,
    machine_to_deb_arch,
    render_appstream_metadata,
    render_desktop_entry,
    render_winget_manifests,
    render_wix_source,
    to_msi_version,
)


class ReleasePackagingTests(unittest.TestCase):
    def test_load_release_metadata_defaults(self) -> None:
        metadata = load_release_metadata()
        self.assertEqual(metadata.package_identifier, "NovaShell.NovaShell")
        self.assertEqual(metadata.package_slug, "nova-shell")

    def test_to_msi_version_uses_first_three_numeric_parts(self) -> None:
        self.assertEqual(to_msi_version("1.2.3.4"), "1.2.3")

    def test_machine_to_deb_arch(self) -> None:
        self.assertEqual(machine_to_deb_arch("x86_64"), "amd64")
        self.assertEqual(machine_to_deb_arch("aarch64"), "arm64")

    def test_render_desktop_entry(self) -> None:
        metadata = load_release_metadata()
        desktop = render_desktop_entry(metadata)
        self.assertIn("Exec=nova-shell", desktop)
        self.assertIn("Terminal=true", desktop)

    def test_render_appstream_metadata(self) -> None:
        metadata = load_release_metadata()
        xml = render_appstream_metadata(metadata)
        self.assertIn("<component", xml)
        self.assertIn(metadata.package_name, xml)

    def test_render_winget_manifests(self) -> None:
        metadata = load_release_metadata()
        manifests = render_winget_manifests(
            metadata,
            __version__,
            "https://example.invalid/nova-shell.msi",
            "ABC123",
            "x64",
        )
        self.assertIn('PackageIdentifier: "NovaShell.NovaShell"', manifests["version"])
        self.assertIn('InstallerUrl: "https://example.invalid/nova-shell.msi"', manifests["installer"])

    def test_render_wix_source_contains_files(self) -> None:
        metadata = load_release_metadata()
        with tempfile.TemporaryDirectory() as tmp:
            bundle = Path(tmp) / "bundle"
            nested = bundle / "deps"
            nested.mkdir(parents=True)
            (bundle / "nova_shell.exe").write_text("exe", encoding="utf-8")
            (nested / "helper.dll").write_text("dll", encoding="utf-8")
            wix = render_wix_source(metadata, __version__, bundle, "nova_shell.exe")
        self.assertIn("Package Name=", wix)
        self.assertIn("nova_shell.exe", wix)
        self.assertIn("helper.dll", wix)

    def test_render_wix_source_includes_intermediate_directories(self) -> None:
        metadata = load_release_metadata()
        with tempfile.TemporaryDirectory() as tmp:
            bundle = Path(tmp) / "bundle"
            nested = bundle / "numpy" / "_core"
            nested.mkdir(parents=True)
            (nested / "multiarray.pyd").write_text("bin", encoding="utf-8")

            wix = render_wix_source(metadata, __version__, bundle, "nova_shell.exe")

        self.assertIn('Name="numpy"', wix)
        self.assertIn('Name="_core"', wix)
        self.assertIn("multiarray.pyd", wix)

    def test_render_wix_source_avoids_path_resolve_for_file_sources(self) -> None:
        metadata = load_release_metadata()
        with tempfile.TemporaryDirectory() as tmp:
            bundle = Path(tmp) / "bundle"
            bundle.mkdir(parents=True)
            target = bundle / "nova_shell.exe"
            target.write_text("exe", encoding="utf-8")
            with patch.object(Path, "resolve", side_effect=AssertionError("resolve should not be called")):
                wix = render_wix_source(metadata, __version__, bundle, "nova_shell.exe")

        self.assertIn(str(target.absolute()), wix)

    def test_format_deb_description(self) -> None:
        text = format_deb_description("Summary", "Line one\n\nLine two")
        self.assertIn("Summary", text)
        self.assertIn(" .", text)


if __name__ == "__main__":
    unittest.main()

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nova_shell import __version__
from release_sbom import SbomArtifact, build_cyclonedx_sbom, collect_environment_components, write_cyclonedx_sbom


class _FakeDistribution:
    def __init__(self, name: str, version: str, *, license_value: str = "", requires: list[str] | None = None) -> None:
        self.metadata = {"Name": name, "License": license_value}
        self.version = version
        self.requires = requires or []


class ReleaseSbomTests(unittest.TestCase):
    def test_build_cyclonedx_sbom_includes_release_artifact_properties(self) -> None:
        payload = build_cyclonedx_sbom(
            package_name="nova-shell",
            version=__version__,
            description="Unified compute runtime",
            license_id="LicenseRef-Proprietary",
            artifacts=[
                SbomArtifact(
                    path="dist/release/linux-x86_64/core/nova-shell.tar.gz",
                    sha256="abc123",
                    size=4096,
                    kind="standalone-archive",
                )
            ],
            dependency_names=["psutil"],
            source_date_epoch=1700000000,
        )

        self.assertEqual(payload["bomFormat"], "CycloneDX")
        self.assertEqual(payload["specVersion"], "1.6")
        self.assertEqual(payload["metadata"]["timestamp"], "2023-11-14T22:13:20Z")

        properties = {entry["name"]: entry["value"] for entry in payload["metadata"]["properties"]}
        self.assertEqual(properties["nova-shell:artifact-count"], "1")
        self.assertEqual(
            properties["nova-shell:artifact:dist/release/linux-x86_64/core/nova-shell.tar.gz:kind"],
            "standalone-archive",
        )
        self.assertEqual(
            properties["nova-shell:artifact:dist/release/linux-x86_64/core/nova-shell.tar.gz:sha256"],
            "abc123",
        )

    def test_write_cyclonedx_sbom_uses_logical_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "artifact.zip"
            artifact.write_text("payload", encoding="utf-8")
            output_path = root / "nova-shell.sbom.cyclonedx.json"

            result = write_cyclonedx_sbom(
                output_path,
                package_name="nova-shell",
                version=__version__,
                description="Unified compute runtime",
                license_id="LicenseRef-Proprietary",
                artifact_paths=[
                    ("dist/release/windows-amd64/core/artifact.zip", artifact, "installer"),
                ],
                dependency_names=[],
                source_date_epoch=1700000000,
            )

            self.assertEqual(result, output_path)
            text = output_path.read_text(encoding="utf-8")
            payload = json.loads(text)

        properties = {entry["name"]: entry["value"] for entry in payload["metadata"]["properties"]}
        self.assertIn("nova-shell:artifact:dist/release/windows-amd64/core/artifact.zip:kind", properties)
        self.assertNotIn(str(root).replace("\\", "\\\\"), text)

    def test_collect_environment_components_follows_declared_dependencies_only(self) -> None:
        fake_distributions = [
            _FakeDistribution("psutil", "5.9.0", license_value="BSD-3-Clause", requires=["typing-extensions>=4.0"]),
            _FakeDistribution("typing-extensions", "4.15.0"),
            _FakeDistribution("torch", "2.10.0"),
        ]
        with patch("release_sbom.metadata.distributions", return_value=fake_distributions):
            components = collect_environment_components(["psutil"])

        self.assertEqual([component["name"] for component in components], ["psutil", "typing-extensions"])


if __name__ == "__main__":
    unittest.main()

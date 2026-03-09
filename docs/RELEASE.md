# Release Guide

Nova-shell wird in zwei Release-Profilen ausgeliefert:

- `core`: reine Standardbibliothek plus CLI-Binary, geeignet als Basispaket.
- `enterprise`: erweitert `core` um `psutil`, `PyYAML`, `pyarrow` und `wasmtime`.

Die GPU-Toolchain bleibt bewusst separat. `pyopencl` und die jeweiligen OpenCL-Treiber sind stark plattform- und vendorabhängig und sollten nicht ungeprüft im Standard-Release mitgebündelt werden.

## Artefakte

Der Release-Build erzeugt:

- `sdist` und `wheel`
- ein standalone Binary auf Basis von Nuitka
- Windows-Installer (`.msi`)
- Linux-Installer (`.AppImage`, `.deb`)
- ein Manifest mit Build-Metadaten
- ein CycloneDX-SBOM (`*.sbom.cyclonedx.json`)
- eine `SHA256SUMS`-Datei
- eine Subject-Checksums-Datei (`*-subjects.checksums.txt`) für Attestations
- optional Authenticode-signierte Windows-Binaries
- optional detached GPG-Signaturen (`.sig`)
- aggregierte Release-Notes (`release-notes.md`)
- GitHub Artifact Attestations für Build-Provenance und SBOM
- optional `winget`-Manifeste für GitHub-Release-URLs

Standardpfad:

```text
dist/release/<os>-<arch>/<profile>/
```

## Lokaler Build

Windows:

```powershell
./scripts/build_windows.ps1 -Profile core
./scripts/build_windows.ps1 -Profile enterprise
./scripts/build_windows.ps1 -Profile core -SourceDateEpoch 1700000000
```

Der Windows-Wrapper lädt `VsDevCmd.bat` automatisch. Direkte Aufrufe von `python scripts/build_release.py ...` sollten auf Windows nur aus einer initialisierten Visual-Studio-Developer-Shell heraus erfolgen.

Linux:

```bash
./scripts/build_linux.sh core
./scripts/build_linux.sh enterprise
SOURCE_DATE_EPOCH=1700000000 ./scripts/build_linux.sh core
```

Direkt per Python:

```bash
python scripts/build_release.py --profile core --mode all --clean
python scripts/build_release.py --profile enterprise --mode all --clean
python scripts/build_release.py --profile core --mode installers
SOURCE_DATE_EPOCH=1700000000 python scripts/build_release.py --profile core --mode all --clean
python scripts/build_release.py --profile core --mode all --base-download-url "https://github.com/<org>/<repo>/releases/download/v0.8.2"
python scripts/generate_release_notes.py --root dist/release --output dist/release/release-notes.md
python scripts/sign_release.py --root dist/release --verify
```

Windows mit Signierung:

```powershell
./scripts/build_windows.ps1 -Profile core -Sign -CertificateFile C:\secrets\nova-shell.pfx -CertificatePassword "<password>"
```

## Voraussetzungen

- Python 3.11 oder 3.12
- Für Nuitka-Standalone:
  - Windows: Visual Studio Build Tools mit C++-Workload und vollständigen Windows-SDK-Headern
  - Linux: funktionierende C-Toolchain und `patchelf`
- Für Windows-MSI:
  - WiX Toolset v4 (`wix`)
- Für Windows-Signierung:
  - `signtool`
  - ein Code-Signing-Zertifikat (`.pfx`) oder ein Zertifikat im Windows-Zertifikatsspeicher
- Für direkte Python-Builds auf Windows:
  - initialisierte MSVC-Umgebung (`VsDevCmd` / `x64 Native Tools PowerShell`)
- Für AppImage:
  - `appimagetool`
- Für `.deb`:
  - `dpkg-deb`
- Für detached Signatures:
  - `gpg`

## Smoke Tests

Standalone-Artefakte werden automatisch verifiziert mit:

- `--version`
- `--no-plugins -c "py 1 + 1"`
- `--no-plugins -c "doctor json"`

## CI/CD

Es gibt zwei Workflows:

- `.github/workflows/ci.yml`
  - Unit-Tests auf Windows und Linux
  - Paket-Build (`sdist`/`wheel`)
  - CLI-Smoke-Checks
- `.github/workflows/release.yml`
  - Build-Matrix für Windows/Linux und `core`/`enterprise`
  - `MSI`, `AppImage`, `.deb` und optional `winget`-Manifest-Generierung
  - CycloneDX-SBOM-Generierung pro Build
  - Ableitung von `SOURCE_DATE_EPOCH` aus dem letzten Git-Commit
  - GitHub Artifact Attestations für Build-Provenance und SBOM
  - optionale Windows-Code-Signierung im Build-Job
  - aggregierte Release-Notes im Publish-Job
  - optionale GPG-Detached-Signaturen im Publish-Job
  - Upload der Artefakte
  - optionales Publishing auf GitHub Releases bei Tag-Builds

Benutzte Secrets:

- `WINDOWS_SIGN_CERT_BASE64` (`.pfx` als Base64)
- `WINDOWS_SIGN_CERT_PASSWORD`
- `WINDOWS_SIGN_SUBJECT_NAME`
- `RELEASE_GPG_PRIVATE_KEY_BASE64` (ASCII-armored Private Key als Base64)
- `RELEASE_GPG_PASSPHRASE`

## Runtime-Hinweise

- `cpp` benötigt lokal weiter `g++`.
- `cpp.sandbox` benötigt lokal weiter `emcc`.
- `doctor` zeigt den Status von `g++`, `emcc`, `cl` und optionalen Modulen an.

## Installer-Struktur

Windows:

- MSI installiert den standalone-Bundle-Inhalt unter `Program Files/Nova-shell`
- Startmenü-Shortcut wird erzeugt
- `winget`-Manifeste werden nur generiert, wenn `--base-download-url` gesetzt ist
- bei aktivierter Signierung werden `.exe`, `.dll` und `.msi` mit `signtool sign` versehen und direkt verifiziert

Linux:

- `.deb` installiert nach `/opt/nova-shell` und legt `/usr/bin/nova-shell` als Symlink an
- `AppImage` enthält `desktop`-Metadaten, Icon und AppStream-Datei
- detached GPG-Signaturen werden im Publish-Job über alle Release-Dateien erzeugt

## Verifikation

Provenance:

```bash
gh attestation verify dist/release/<os>-<arch>/<profile>/<artifact> --repo <org>/<repo>
```

SBOM:

```bash
gh attestation verify dist/release/<os>-<arch>/<profile>/<artifact> --repo <org>/<repo> --predicate-type https://cyclonedx.org/bom
```

Detached Signatures:

```bash
gpg --verify dist/release/<...>/<artifact>.sig dist/release/<...>/<artifact>
```

Windows Authenticode:

```powershell
signtool verify /pa dist\release\<...>\nova-shell.msi
```

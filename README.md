# Nova-shell

Nova-shell ist eine **Unified Compute & Data Orchestration Runtime** mit polyglotten Engines, DSL, AOT-Pipelines, Lineage, Mesh-Offloading und Security-Enforcement.
<img width="1487" height="781" alt="image" src="https://github.com/user-attachments/assets/18082e0a-d54f-4f3d-a8d9-9b0198e471ad" />

## Nächste Ebene: 5 professionell umgesetzte Enterprise-Module

### 1) NovaZero — Unified Zero-Copy Memory Bridge
- Neuer globaler Shared-Memory-Pool `NovaZeroPool`.
- Kommandos:
  - `zero put <text>`
  - `zero put-arrow <csv>`
  - `zero get <handle>`
  - `zero list`
  - `zero release <handle>`
- Arrow-Pfade nutzen IPC-Streams in Shared Memory für engine-übergreifenden Austausch ohne JSON-Roundtrips.

### 2) NovaSynth — AI-Native Engine Selector & Autotuner
- Neue Runtime-Komponente `NovaSynth` (heuristisch + Telemetrie-gestützt).
- Kommandos:
  - `synth suggest <code>`
  - `synth autotune <code>`
- Nutzt Mustererkennung + Optimizer-Signale, um Workloads dynamisch auf `py/cpp/gpu/mesh` auszurichten.

### 3) NovaPulse — Real-Time Observability & Visual Debugger Surface
- Vision API erweitert mit Pulse-State-Daten:
  - `GET /pulse/state`
- CLI-Kommandos:
  - `pulse status`
  - `pulse snapshot`
- Liefert Bottleneck-Sicht (Top-Latenzen), Event-Tails und Trigger/Topic-Überblick.

### 4) NovaFlow — Distributed Reactive Workflows
- Neuer verteilter Flow-Layer (`dflow`) zusätzlich zu lokalen `reactive`-Triggern.
- Kommandos:
  - `dflow subscribe <event> <pipeline>`
  - `dflow publish <event> <payload> [--broadcast]`
  - `dflow list`
- Vision-Endpunkt `POST /flow/event` erlaubt Mesh-weite Eventzustellung.

### 5) NovaGuard Sandbox Isolation (WASM-First)
- C++ kann standardmäßig in Sandbox laufen (`WASM-first`) statt nativem Host-Binary.
- Kommandos:
  - `guard sandbox on|off|status`
  - `cpp.sandbox <cpp_code>`
- Erweiterte Guard/eBPF-Flows:
  - `guard ebpf-status`
  - `guard ebpf-compile <policy>`
  - `guard ebpf-enforce <policy>`
  - `guard ebpf-release`

---

## Weitere Kernfeatures

- Engines: `py/python`, `cpp`, `gpu`, `wasm`, `remote`, `sys`.
- NovaGraph AOT (`graph aot|run|show`) inkl. C++-Expr-Fusion.
- NovaLens CAS-Lineage (`lens list|last|show|replay`).
- Mesh Intelligence (`mesh beat`, `mesh intelligent-run`).
- NovaScript 2.0 Contracts + Reactive Hooks (`watch`, `ns.emit`, `ns.check`).
- Fabric inkl. Remote/RDMA-orientierter Transferpfade.

## Quickstart

```bash
python -m nova_shell
```

oder nach Installation:

```bash
nova-shell
```

Einzelkommando ohne REPL:

```bash
nova-shell --no-plugins -c "py 1 + 1"
```

Runtime-Diagnose:

```bash
nova-shell doctor
nova-shell doctor json
```

Lernpfad mit vielen Programmierbeispielen:

[Tutorial.md](Tutorial.md)

## Packaging & Release

- Paket-Metadaten liegen in `pyproject.toml`.
- CLI-Entry-Point: `nova-shell`.
- Release-Profile:
  - `core`
  - `enterprise`
- Standalone-Builds erfolgen mit Nuitka.
- Installer-Artefakte:
  - Windows: `MSI` plus optionale `winget`-Manifeste
  - Linux: `AppImage` plus `.deb`
- Supply-Chain-Artefakte:
  - CycloneDX-SBOM pro Build (`*.sbom.cyclonedx.json`)
  - Subject-Checksums für Attestations (`*-subjects.checksums.txt`)
  - GitHub Artifact Attestations für Provenance und SBOM
- Windows-Wrapper:
  - `./scripts/build_windows.ps1` lädt `VsDevCmd` automatisch, damit MSVC-Header wie `excpt.h` im Build verfügbar sind
- Signierung & Release-Notes:
  - Windows Authenticode via `signtool`
  - detached GPG signatures via `scripts/sign_release.py`
  - aggregierte Release-Notes via `scripts/generate_release_notes.py`
- Cross-Platform-Wrapper:
  - Windows: `./scripts/build_windows.ps1`
  - Linux: `./scripts/build_linux.sh`
- Vollständige Release-Dokumentation: `docs/RELEASE.md`

Beispiele:

```powershell
./scripts/build_windows.ps1 -Profile core
./scripts/build_windows.ps1 -Profile enterprise
./scripts/build_windows.ps1 -Profile core -SourceDateEpoch 1700000000
```

```bash
./scripts/build_linux.sh core
./scripts/build_linux.sh enterprise
SOURCE_DATE_EPOCH=1700000000 ./scripts/build_linux.sh core
```

Direkter Installer-Build:

```bash
python scripts/build_release.py --profile core --mode installers
SOURCE_DATE_EPOCH=1700000000 python scripts/build_release.py --profile core --mode all --clean
python scripts/build_release.py --profile core --mode all --base-download-url "https://github.com/<org>/<repo>/releases/download/v0.8.0"
python scripts/generate_release_notes.py --root dist/release --output dist/release/release-notes.md
python scripts/sign_release.py --root dist/release --verify
```

Verifikation:

```bash
gpg --verify dist/release/<...>/<artifact>.sig dist/release/<...>/<artifact>
gh attestation verify dist/release/<...>/<artifact> --repo <org>/<repo>
gh attestation verify dist/release/<...>/<artifact> --repo <org>/<repo> --predicate-type https://cyclonedx.org/bom
```

```powershell
signtool verify /pa dist\release\<...>\nova-shell.msi
```

## Tests

```bash
python -m unittest discover -s tests -v
```

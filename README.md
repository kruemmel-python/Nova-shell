# Nova-shell

Nova-shell ist eine **Unified Compute & Data Orchestration Runtime** mit polyglotten Engines, DSL, AOT-Pipelines, Lineage, Mesh-Offloading und Security-Enforcement.

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
python nova_shell.py
```

## Tests

```bash
python -m unittest discover -s tests -v
```

# Nova-shell

Nova-shell ist eine **Unified Compute & Data Orchestration Runtime** mit polyglotten Engines, Pipeline-Optimierung, NovaScript-DSL und Observability.

## Enterprise-Upgrade: 5 vollständig implementierte Bausteine

### 1) NovaGraph — AOT-Kompilierung von Cross-Engine-Pipelines
- Neuer `graph`-Befehl:
  - `graph aot <pipeline>`
  - `graph run <pipeline>`
  - `graph show <graph_id>`
- AOT-Optimizer erkennt und fusioniert aufeinanderfolgende `cpp.expr`-Stages in `cpp.expr_chain`.
- Für fusionierte C++-Expr-Pipelines wird ein gemeinsamer C++-Codepfad erzeugt.

### 2) NovaLens — Time-Travel Debugging & Data Lineage (CAS)
- Persistente Lineage via SQLite (`.nova_lens/lineage.db`) und Content-Addressable Storage (`.nova_lens/cas`).
- Jeder Stage-Output wird gehasht (SHA-256) und versioniert gespeichert.
- Lens-Befehle:
  - `lens list [n]`
  - `lens last`
  - `lens show <id>`
  - `lens replay <id>`

### 3) NovaMesh Intelligence — Latency-Aware Task Offloading
- Mesh-Worker besitzen nun Telemetrie-Metadaten: `latency_ms`, `data_handles`, `last_seen`.
- Neue Mesh-Befehle:
  - `mesh beat <worker_url> [latency_ms] [handle1,handle2]`
  - `mesh intelligent-run <capability> <command> [--handle h]`
- Scheduler priorisiert Datenlokalität + Latenz + Last statt nur Round-Robin/Load.

### 4) NovaScript Reactive Hooks — Distributed Stream Processing
- NovaScript-Grammatik erweitert um `watch <variable>:`-Hooks.
- Hook-Execution wird bei Variablenänderung ausgelöst.
- Runtime-Steuerung:
  - `ns.exec ...` / `ns.run ...` lädt Watch-Hooks
  - `ns.emit <variable> <value>` triggert Hooks aktiv
- Zusätzlich weiter vorhanden: `reactive on-file/on-sync` auf Shell-Ebene.

### 5) NovaGuard eBPF-Enforcement — Kernel-Level vorbereitete Enforcement-Schicht
- Dynamische Policy-Ladung und Enforcement-Modi:
  - `guard load <policy.yaml|policy.json>`
  - `guard ebpf-status`
  - `guard ebpf-compile <policy>`
  - `guard ebpf-enforce <policy>`
  - `guard ebpf-release`
- Bei aktivem Enforcement werden geblockte Muster in `sys`/`cpp` vor Ausführung verhindert.
- eBPF-Availability wird erkannt; ohne Kernel-Bindings läuft Userspace-Enforcement-Fallback.

---

## Weitere Runtime-Features

- Engines: `py/python`, `cpp`, `gpu`, `wasm`, `remote`, `sys`.
- Typed/streaming Pipelines, Generatoren, `parallel`, `watch`.
- Mesh, Fabric (`put/get`, `remote-put/get`, `rdma-put/get`), Flow State, CRDT Sync.
- Optimizer (`opt suggest/run`) und NovaScript Contracts + `ns.check`.
- Vision API: `/events`, `/graph`, `/commands`, `/lsp/completions`, `/fabric/*`.

## Quickstart

```bash
python nova_shell.py
```

## Tests

```bash
python -m unittest discover -s tests -v
```

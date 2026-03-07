# Nova-shell

Nova-shell ist eine **Unified Compute & Data Orchestration Runtime** mit polyglotten Engines, Pipeline-Orchestrierung, NovaScript-DSL und Observability.

## Vollständig umgesetzte 5 Weiterentwicklungen

### 1) NovaOptimizer — Predictive Multi-Engine Steering
- Telemetrie-basierte Engine-Vorschläge (`events` + Ressourcensampling).
- Kommando: `opt suggest <task> [payload]`.
- Autonome Delegation: `opt run <task> [payload]`.
- Berücksichtigt u.a. Payload-Größe, Keywords (z. B. matrix/tensor), CPU-Last und Mesh-Verfügbarkeit.

### 2) NovaFabric — Zero-Copy RDMA Bridge (professionelles Fallback-Design)
- Lokaler Shared-Memory-Fabric: `fabric put/get`, `fabric put-arrow`.
- Remote MVP: `fabric remote-put`, `fabric remote-get`.
- RDMA-kompatible Bridge-API mit Binary-Transport:
  - `fabric rdma-put <url> <file>`
  - `fabric rdma-get <url> <handle> <out_file>`
- Vision-HTTP stellt passende Endpunkte bereit (`/fabric/put`, `/fabric/get`, `/fabric/put-bytes`, `/fabric/get-bytes`).

### 3) Reactive NovaFlow — Event-Driven Pipeline Triggers
- Neuer Trigger-Manager für autonome Ausführung.
- Dateibasierte Trigger: `reactive on-file <glob> <pipeline> [--continuous]`.
- Sync-basierte Trigger: `reactive on-sync <counter> <threshold> <pipeline> [--continuous]`.
- Verwaltung: `reactive list`, `reactive stop <id>`, `reactive clear`.

### 4) NovaGuard — eBPF-orientierte Sandboxing & Policy Enforcement
- Erweiterter Guard mit Policy-Store und optionaler eBPF-Fähigkeitserkennung.
- Kommandos:
  - `guard list`
  - `guard set <policy>`
  - `guard load <policy.yaml|policy.json>`
  - `guard ebpf-status`
- Stage-Enforcement nutzt Built-in-Policies plus geladene Regeln.

### 5) NovaScript 2.0 — Strongly Typed Contract Pipelines
- Vertrags-Syntax in NovaScript:
  - Getypte Assignments: `rows: object_stream = data load file.csv`
  - Output-Contracts: `py len(_) -> object`
- Interpreter validiert Contracts zur Laufzeit und bricht bei Typverletzungen mit klarer Fehlermeldung ab.
- Neues Prüfkommando: `ns.check <script.ns>` (liefert Contract- und Node-Statistiken).

---

## Weitere zentrale Runtime-Features

- Engines: `py/python`, `cpp`, `gpu`, `wasm`, `remote`, `sys`.
- Mesh Scheduling: `mesh add/list/run`.
- Flow State + CRDT: `flow ...`, `sync ...`.
- Temporal Lineage: `lens list|last|show`.
- PipelineGraph + Stage-Fusion (`py_chain`), Streams, Generatoren, `parallel`.
- Vision API: `/events`, `/graph`, `/commands`, `/lsp/completions?prefix=...`.

## Quickstart

```bash
python nova_shell.py
```

## Beispiele

```text
nova> opt suggest matrix_mul "1+2"
{"engine":"gpu", ...}

nova> reactive on-file "input/*.csv" "data load _ | py len(_)"
{"id":"...","kind":"file"}

nova> guard ebpf-status
{"available":false,"mode":"userspace-fallback"}

nova> ns.check typed_pipeline.ns
{"nodes":3,"contracts":2,...}
```

## Tests

```bash
python -m unittest discover -s tests -v
```

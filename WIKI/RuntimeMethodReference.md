# Runtime Method Reference

## Zweck

Diese Seite fasst die wichtigsten Methoden von `NovaRuntime` zusammen.
Sie ist keine automatische API-Generierung, sondern eine handkuratierte Referenz fuer die Methoden, die fuer Ausfuehrung, Betrieb und Erweiterung relevant sind.

Modul: `nova.runtime.runtime`

## Kernobjekte

- `NovaRuntime`
- `CompiledNovaProgram`
- `NovaRuntimeResult`
- `RuntimeContext`

## Methoden und Schnittstellen

### Programmladen und Ausfuehrung

| Methode | Zweck | Typische Nutzung |
| --- | --- | --- |
| `load(path)` | Laedt ein `.ns`-Programm ueber die Toolchain. | Projekte und modulare Programme |
| `compile(program_or_ast)` | Erzeugt ein `CompiledNovaProgram`. | Vor Visualisierung oder Analyse |
| `run(program_or_path)` | Fuehrt ein Programm komplett aus. | Standardpfad fuer deklarative Ausfuehrung |
| `execute_flow(name, program=...)` | Startet gezielt einen Flow. | Partielle Workflows |
| `emit(event_name, payload=None)` | Publiziert ein Event in die Runtime. | Event-getriebene Automatisierung |
| `snapshot()` | Erstellt einen Laufzeit-Snapshot. | Recovery und Debugging |
| `resume(snapshot_or_path)` | Setzt eine Runtime aus einem Snapshot fort. | Wiederanlauf nach Fehlern |

### Beispiel

```python
from nova.runtime.runtime import NovaRuntime

runtime = NovaRuntime()
program = runtime.load("examples/market_radar.ns")

compiled = runtime.compile(program)
result = runtime.run(program)
print(result.status)
```

### Queue, Scheduler und durable Flows

| Methode | Zweck |
| --- | --- |
| `enqueue_flow(flow_name, program=..., priority=...)` | Legt einen Flow in die durable Queue. |
| `schedule_flow(flow_name, cron=..., interval=...)` | Plant einen Flow periodisch ein. |
| `schedule_event(event_name, flow_name, ...)` | Verknuepft Event und geplante Ausfuehrung. |
| `scheduler_tick()` | Fuehrt einen Schedulerdurchlauf aus. |
| `run_pending_tasks()` | Arbeitet wartende Queue-Eintraege ab. |
| `list_queue_tasks()` | Listet Task-Zustand und Historie. |
| `list_schedules()` | Gibt aktive Schedules zurueck. |
| `replay_event_log()` | Spielt Event-Logs erneut ab. |

### Beispiel

```python
runtime.enqueue_flow("radar", program=program, priority="high")
runtime.scheduler_tick()
runtime.run_pending_tasks()
```

### Security, Identity und Trust

| Methode | Zweck |
| --- | --- |
| `register_tenant(name, namespace=...)` | Erstellt einen Tenant. |
| `select_tenant(name)` | Schaltet den aktiven Tenant um. |
| `issue_token(subject, roles=...)` | Erstellt ein Runtime-Token. |
| `login(subject, password=None, token=None)` | Startet eine Runtime-Sitzung. |
| `logout()` | Beendet die aktuelle Sitzung. |
| `store_secret(name, value, namespace=...)` | Speichert ein Secret verschluesselt. |
| `set_tls_profile(name, certificate=..., key=...)` | Setzt ein TLS-Profil. |
| `set_trust_policy(name, rules=...)` | Konfiguriert Trust-Regeln. |
| `onboard_worker(node_id, csr_or_certificate=...)` | Bindet einen Worker sicher an. |
| `rotate_worker_certificate(node_id)` | Erneuert Worker-Zertifikate. |
| `create_certificate_authority(name, ...)` | Erzeugt eine CA. |
| `issue_certificate(common_name, ...)` | Stellt Zertifikate aus. |
| `revoke_certificate(serial)` | Sperrt Zertifikate. |

### Service Fabric und Traffic Plane

| Methode | Zweck |
| --- | --- |
| `install_package(name, source=..., version=...)` | Registriert ein Paket fuer Wiederverwendung oder Deployment. |
| `deploy_service(name, package=..., image=..., replicas=...)` | Erstellt oder aktualisiert einen Service. |
| `list_services()` | Listet bekannte Services. |
| `list_packages()` | Listet registrierte Pakete. |
| `discover_service(name)` | Liefert Service-Discovery-Informationen. |
| `scale_service(name, replicas)` | Skaliert einen Service. |
| `start_traffic_proxy(host, port)` | Startet die Traffic Plane. |
| `route_service_request(service, path="/", method="GET")` | Testet oder fuehrt Traffic-Routing aus. |

### Beispiel

```python
runtime.install_package("analytics", source="./packages/analytics", version="1.0.0")
runtime.deploy_service("analytics-api", package="analytics", replicas=2)
runtime.scale_service("analytics-api", 4)
```

### Observability und API

| Methode | Zweck |
| --- | --- |
| `start_control_api(host="127.0.0.1", port=...)` | Startet die HTTP-Control-Plane. |
| `stop_control_api()` | Stoppt die API. |
| `control_api_status()` | Liefert API-Statusdaten. |
| `export_metrics(format="prometheus")` | Exportiert Laufzeitmetriken. |

### Konsens, Replikation und State

| Methode | Zweck |
| --- | --- |
| `consensus_status()` | Zeigt Leader, Term und Peer-Zustand. |
| `register_consensus_peer(peer_id, endpoint)` | Fuegt einen Peer hinzu. |
| `list_consensus_peers()` | Listet bekannte Peers. |
| `consensus_log()` | Liefert den replizierten Konsens-Log. |
| `consensus_snapshot()` | Erzeugt oder liest einen Snapshot. |
| `start_consensus_election()` | Startet eine Wahl. |
| `send_consensus_heartbeats()` | Sendet Heartbeats an Peers. |
| `compact_consensus_log()` | Verdichtet den Konsens-Log. |
| `install_consensus_snapshot(peer_id, snapshot=...)` | Installiert einen Snapshot bei einem Peer. |
| `sync_consensus()` | Synchronisiert den Konsenszustand. |
| `consensus_request_vote(payload)` | RPC fuer Vote-Anfragen. |
| `consensus_append_entries(payload)` | RPC fuer Log-Replikation. |
| `register_replica_peer(peer_id, endpoint)` | Registriert Event-/State-Replikation. |
| `list_replica_peers()` | Listet Replikationsziele. |
| `list_replicated_records()` | Listet replizierte Event-/State-Datensaetze. |
| `replay_state_log()` | Spielt den State-Log erneut ab. |
| `list_state()` | Gibt den persistierten Zustand aus. |
| `list_workflow_runs()` | Zeigt historische Workflow-Ausfuehrungen. |
| `replay_workflow_run(run_id)` | Wiederholt einen frueheren Lauf. |

### Agenten und AI-Plattform

| Methode | Zweck |
| --- | --- |
| `register_prompt_version(agent, version, prompt)` | Speichert eine neue Prompt-Version. |
| `list_prompt_versions(agent)` | Listet bekannte Prompt-Staende. |
| `search_agent_memory(agent, query)` | Sucht im verteilten Agenten-Speicher. |
| `list_agent_evals(agent=None)` | Listet Eval-Laeufe und Scores. |

### Toolchain und Entwickler-Workflows

| Methode | Zweck |
| --- | --- |
| `write_lockfile(path)` | Schreibt die aktuelle Modulaufloesung als Lockfile. |
| `publish_toolchain_package(name, path, version)` | Publiziert ein Toolchain-Paket. |
| `list_toolchain_packages()` | Listet bekannte Pakete. |
| `format_source(source_or_path)` | Formatiert Nova-Quelltext. |
| `lint_source(source_or_path)` | Fuehrt statische Diagnosen aus. |
| `toolchain_symbols(path)` | Liefert Symbolinformationen fuer Editoren. |
| `toolchain_hover(path, line, column)` | Liefert Hover-Dokumentation. |
| `run_program_tests(path_or_program)` | Startet deklarative Tests. |

### Beispiel

```python
runtime.write_lockfile("nova.lock")
diagnostics = runtime.lint_source("examples/market_radar.ns")
formatted = runtime.format_source("examples/market_radar.ns")
```

### Betrieb, Recovery und Tests

| Methode | Zweck |
| --- | --- |
| `create_backup(destination)` | Erstellt ein Runtime-Backup. |
| `restore_backup(path)` | Stellt den Runtime-Zustand wieder her. |
| `validate_migrations()` | Prueft Persistenz- und Schemakompatibilitaet. |
| `set_failpoint(name, state=True)` | Aktiviert gezielte Fehlerpunkte fuer Tests. |
| `list_failpoints()` | Zeigt aktive Failpoints. |
| `run_load_test(profile="default")` | Startet einen Lasttest. |

## CLI

Methoden dieser Seite werden typischerweise ueber `ns.run`, `ns.control`, `ns.snapshot`, `ns.resume` und Toolchain-Kommandos genutzt.

## API

Die API-nahen Methoden sind vor allem:

- `start_control_api`
- `stop_control_api`
- `control_api_status`
- `export_metrics`

## Beispiele

### Praktisches Betriebsbeispiel

```python
from nova.runtime.runtime import NovaRuntime

runtime = NovaRuntime()
runtime.start_control_api(port=9850)
runtime.create_backup(".nova/backups/nightly")
print(runtime.export_metrics())
```

## Verwandte Seiten

- [ClassReference](./ClassReference.md)
- [APIReference](./APIReference.md)
- [ExamplesAndRecipes](./ExamplesAndRecipes.md)
- [PageTemplate](./PageTemplate.md)

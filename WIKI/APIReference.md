# API Reference

## Zweck

Die HTTP-Control-Plane-API wird von `NovaControlPlaneAPIServer` bereitgestellt.
Sie macht Runtime-, Queue-, Service-, Traffic-, Agent- und Betriebsfunktionen ueber HTTP verfgbar.

## Kernobjekte

- `nova.runtime.api.NovaControlPlaneAPIServer`
- `NovaRuntime`
- `DurableControlPlane`
- `ControlPlaneConsensus`
- `ServiceTrafficPlane`

## Methoden und Schnittstellen

Wichtige API-Server-Methoden:

- `start()`
- `stop()`
- `status()`

## CLI

Typische Wege zur API ueber die CLI:

- `ns.control api start`
- `ns.control api stop`
- `ns.control metrics`
- `ns.status`

## API

### Health und Status

| Methode | Pfad | Zweck |
| --- | --- | --- |
| `GET` | `/health` | Healthcheck und API-Status |
| `GET` | `/status` | umfassender Runtime-Status |

### Metrics und Traces

| Methode | Pfad | Zweck |
| --- | --- | --- |
| `GET` | `/metrics/prometheus` | Prometheus-Format |
| `GET` | `/metrics/otlp` | OTLP-artiger JSON-Export |
| `GET` | `/traces` | Trace-Liste |
| `GET` | `/alerts` | aktive Alerts |

### Queue und Scheduling

| Methode | Pfad | Zweck |
| --- | --- | --- |
| `GET` | `/queue` | Queue-Tasks listen |
| `POST` | `/queue/enqueue` | Flow in Queue stellen |
| `POST` | `/queue/run` | Queue sofort drainen |
| `GET` | `/schedules` | Schedules listen |
| `POST` | `/schedules/flow` | periodischen Flow anlegen |
| `POST` | `/schedules/event` | periodisches Event anlegen |

### Events, State und Workflows

| Methode | Pfad | Zweck |
| --- | --- | --- |
| `GET` | `/events` | Event-Log lesen |
| `GET` | `/state` | State-Eintraege lesen |
| `GET` | `/workflows` | Workflow-Laeufe listen |

### Replication und Consensus

| Methode | Pfad | Zweck |
| --- | --- | --- |
| `GET` | `/replication/peers` | Replikationspeers |
| `GET` | `/replication/records` | replizierte Records |
| `GET` | `/consensus/status` | Konsensstatus |
| `GET` | `/consensus/peers` | Konsenspeers |
| `GET` | `/consensus/log` | Konsenslog |
| `GET` | `/consensus/snapshot` | Snapshot |

### Services und Traffic

| Methode | Pfad | Zweck |
| --- | --- | --- |
| `GET` | `/services` | Services listen |
| `GET` | `/services/discover` | Service-Discovery |
| `GET` | `/services/ingress` | Ingress-Regeln |
| `GET` | `/services/configs` | Configs |
| `GET` | `/services/volumes` | Volumes |
| `GET` | `/traffic/routes` | Traffic-Routen |
| `GET` | `/traffic/probes` | Health-Probes |
| `GET` | `/traffic/mounts` | Secret-Mounts |
| `GET` | `/traffic/proxy` | Proxy-Status |

### Toolchain, Agents und Operations

| Methode | Pfad | Zweck |
| --- | --- | --- |
| `GET` | `/toolchain/packages` | Registry-Pakete |
| `GET` | `/agents/prompts` | Prompt-Versionen |
| `GET` | `/agents/evals` | Agent-Evaluationen |
| `GET` | `/agents/memory` | Agent-Memory durchsuchen |
| `GET` | `/operations/backups` | Backups |
| `GET` | `/operations/failpoints` | Failpoints |
| `GET` | `/packages` | Packages |
| `GET` | `/executors` | Executor-Status |
| `GET` | `/executors/stream` | Stream-/Jobdaten |

## Beispiele

```bash
curl http://127.0.0.1:8781/health
curl http://127.0.0.1:8781/status
curl "http://127.0.0.1:8781/traces?limit=20"
```

## Verwandte Seiten

- [NovaRuntime](./NovaRuntime.md)
- [RuntimeMethodReference](./RuntimeMethodReference.md)
- [ExamplesAndRecipes](./ExamplesAndRecipes.md)
- [PageTemplate](./PageTemplate.md)

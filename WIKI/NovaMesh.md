# Nova Mesh

## Zweck

Nova Mesh ist die verteilte Ausfuehrungsschicht von Nova-shell.
Sie verbindet:

- Worker-Registrierung
- Capability-basierten Dispatch
- lokale und entfernte Executor-Pfade
- Heartbeats und Health
- verteilte Aufgabenverteilung

## Kernobjekte

| Klasse | Rolle |
| --- | --- |
| `WorkerNode` | Repräsentation eines Workers |
| `MeshRegistry` | Registry und Dispatch-Logik |
| `PersistentMeshControlPlane` | persistente Mesh-Task-Historie |
| `ExecutorTask` | standardisierte Arbeitsanforderung |
| `ExecutorResult` | standardisiertes Ergebnis |
| `MeshWorkerServer` | lokaler Worker-Prozess in der CLI-Runtime |
| `NativeExecutorManager` | lokale Executor-Verwaltung |

## Methoden und Schnittstellen

Wichtige Registry- und Worker-Schnittstellen:

- Worker registrieren
- Heartbeats senden
- Capabilities matchen
- Tasks dispatchen
- Executor-Ergebnisse zurueckgeben

### Worker-Lebenszyklus

```text
register -> heartbeat -> capability match -> task dispatch -> result
```

### Capability-Modell

Typische Capabilities:

- `py`
- `cpp`
- `gpu`
- `wasm`
- `ai`

## CLI

Typische Mesh-Kommandos:

```text
mesh start-worker --caps py,gpu
mesh beat
mesh intelligent-run py 1 + 1
mesh stop-worker
```

## API

Mesh-relevante API-Bereiche:

- Konsens- und Peer-Endpunkte
- Executor-Status
- Replikationsstatus

## Beispiele

### Declarative Runtime und Mesh

Relevante Metadaten fuer Placement:

- `capability`
- `selector`
- `tenant`
- `namespace`
- `require_tls`

### Python-Beispiel

```python
from nova.mesh.registry import MeshRegistry, WorkerNode

registry = MeshRegistry()
registry.register(
    WorkerNode(
        node_id="gpu-1",
        endpoint="http://127.0.0.1:9040",
        capabilities={"gpu", "py"},
    )
)
```

## Verwandte Seiten

- [ClassReference](./ClassReference.md)
- [NovaRuntime](./NovaRuntime.md)
- [APIReference](./APIReference.md)
- [PageTemplate](./PageTemplate.md)

# Nova Mesh

## Zweck

Nova Mesh ist die verteilte Ausfuehrungsschicht von Nova-shell.
Sie verbindet Worker-Registrierung, Capability-basierten Dispatch, lokale und entfernte Executor-Pfade, Health-Signale und standardisierte Aufgabenverteilung.

## Kernobjekte

| Klasse | Rolle |
| --- | --- |
| `WorkerNode` | Repräsentation eines Workers mit Endpoint, Capabilities und Metadaten |
| `MeshRegistry` | Registry, Auswahl und Dispatch-Logik |
| `PersistentMeshControlPlane` | persistente Mesh-Task- und Worker-Historie |
| `ExecutorTask` | standardisierte Arbeitsanforderung |
| `ExecutorResult` | standardisiertes Ergebnis |
| `MeshWorkerServer` | Worker-Prozess in der CLI-Runtime |
| `NativeExecutorManager` | Verwaltung lokaler nativer Executor |
| `FederatedLearningMesh` | signierte Invariant-Updates, Broadcast und Apply |

## Worker-Lebenszyklus

```text
register
  ->
heartbeat
  ->
capability match
  ->
task dispatch
  ->
result / status / retry
```

## Methoden und Schnittstellen

Wichtige Mesh-Operationen:

- Worker registrieren
- Heartbeats senden
- Capabilities matchen
- Tasks dispatchen
- Ergebnisse zurueckgeben
- Health und Status auswerten

## Capability-Modell

Typische Capabilities:

- `py`
- `cpp`
- `gpu`
- `wasm`
- `ai`

Diese Capabilities steuern, welche Worker fuer welche Aufgaben in Frage kommen.

## CLI

Typische Mesh-Kommandos:

```text
mesh start-worker --caps py,gpu
mesh beat
mesh intelligent-run py 1 + 1
mesh stop-worker
```

Je nach Aufbau kann zusaetzlich mit `mesh add`, `mesh list` oder Control-Plane-Kommandos gearbeitet werden.

Fuer die Federated-Schicht kommen dazu:

```text
mesh federated status
mesh federated history 10
mesh federated publish --statement "..." --broadcast
mesh federated chronik-latest --broadcast
```

## API

Mesh-relevante API-Bereiche umfassen:

- Worker- und Registry-Zustaende
- Konsens- und Peer-Endpunkte
- Executor-Status
- Replikations- und Dispatch-Status

Details stehen in [APIReference](./APIReference.md).

## Testbare Beispiele

### Worker lokal starten

```powershell
mesh start-worker --caps py,gpu
mesh beat
```

### Registry aus Python pruefen

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

### Deklarative Platzierungsmetadaten

Relevante Metadaten in `.ns`-Programmen:

- `capability`
- `selector`
- `tenant`
- `namespace`
- `require_tls`

### Federated Invariant Broadcast

```powershell
mesh federated publish --statement "Edge anomaly detector learned a new invariant" --namespace swarm --project lab --broadcast
mesh federated history 5
```

### Same-host Zero-Copy via `zero`

```powershell
zero put invariant-payload
mesh federated publish --statement "Shared invariant" --handle <HANDLE> --size <SIZE> --type text --same-host
```

## Typische Fehler und Fragen

### Warum wird ein Task nicht verteilt?

Oft passt keine Capability, der Worker ist nicht registriert oder Policy- und Trust-Anforderungen verhindern den Dispatch.

### Wann ist Mesh ueberhaupt relevant?

Sobald Last, Spezialisierung oder Isolation nicht mehr nur lokal abgebildet werden sollen.

### Was pruefe ich zuerst?

1. Worker-Status
2. Heartbeats
3. Capability-Match
4. Trust- und TLS-Anforderungen

## Verwandte Seiten

- [MeshAndDistributedExecution](./MeshAndDistributedExecution.md)
- [NovaRuntime](./NovaRuntime.md)
- [ZeroCopyFederatedLearningMesh](./ZeroCopyFederatedLearningMesh.md)
- [SecurityAndTrust](./SecurityAndTrust.md)
- [APIReference](./APIReference.md)

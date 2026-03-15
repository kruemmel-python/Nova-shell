# System Overview

## Zweck

Diese Seite ordnet die wichtigsten Subsysteme von Nova-shell ein.
Sie ist die kompakte technische Uebersicht fuer Leser, die zunaechst die Systemschichten und ihre Rollen verstehen wollen.

## Kernobjekte

### Subsysteme im Projekt

| Bereich | Rolle | Zentrale Klassen |
| --- | --- | --- |
| CLI | interaktive Nutzung, Routing und lokale Befehle | `NovaShell`, `CommandResult` |
| Engines | lokale Ausfuehrung fuer Compute und Daten | `PythonEngine`, `CppEngine`, `GPUEngine`, `WasmEngine`, `DataEngine`, `SystemEngine` |
| Sprache | deklarative Beschreibung von Ressourcen und Flows | `NovaParser`, `NovaAST` |
| Graph Engine | AST-zu-DAG-Kompilation | `NovaGraphCompiler`, `ExecutionGraph` |
| Runtime | Flow-Ausfuehrung und Zustand | `NovaRuntime`, `RuntimeContext` |
| Agents | modellgestuetzte Aufgaben | `AgentRuntime`, `AgentSpecification`, `AgentTask` |
| Memory | Wissens- und Suchschicht | `NovaVectorMemory`, `DistributedMemoryStore` |
| Mesh | verteilte Worker | `MeshRegistry`, `MeshWorkerServer` |
| Control Plane | Queue, Scheduling, API | `DurableControlPlane`, `NovaControlPlaneAPIServer` |
| Service Fabric | Services und Packages | `ServiceFabric`, `ServiceTrafficPlane` |
| Security | Rollen, Secrets, TLS | `SecurityPlane`, `RuntimePolicy` |

## Methoden und Schnittstellen

### Betriebsmodi

- interaktive Shell-Nutzung
- deklarative `.ns`-Programmausfuehrung
- lokale AI- und Agentenausfuehrung
- verteilte Worker-Ausfuehrung
- Service- und Traffic-Steuerung
- API- und Control-Plane-Betrieb

### Daten- und Kontrollfluesse

#### Datenfluss

```text
Dataset -> Tool -> Agent -> Output -> Memory
```

#### Kontrollfluss

```text
Event -> Flow -> Graph Closure -> Node Execution -> Event
```

## CLI

Subsysteme werden in der Praxis vor allem ueber diese Kommandos sichtbar:

- `py`, `cpp`, `gpu`, `wasm`
- `agent`
- `atheria`
- `mesh`
- `ns.run`
- `ns.control`

## API

Die HTTP-Control-Plane exponiert Runtime-, Queue-, Service-, Mesh- und Observability-Zustaende.
Details stehen in [APIReference](./APIReference.md).

## Beispiele

### Wichtige Einstiegspunkte

- `nova_shell.py`
- `nova/parser/parser.py`
- `nova/graph/compiler.py`
- `nova/runtime/runtime.py`
- `nova/runtime/api.py`
- `nova/agents/runtime.py`
- `nova/mesh/registry.py`

## Verwandte Seiten

- [Architecture](./Architecture.md)
- [ComponentModel](./ComponentModel.md)
- [ClassReference](./ClassReference.md)
- [PageTemplate](./PageTemplate.md)

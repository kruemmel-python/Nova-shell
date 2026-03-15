# System Overview

## Zweck

Diese Seite ordnet die wichtigsten Subsysteme von Nova-shell ein.
Sie ist die kompakte technische Uebersicht fuer Leser, die zuerst die Systemschichten, ihre Rollen und ihre Beziehungen verstehen wollen.

## Schichten des Systems

| Schicht | Rolle | Typische Einstiegspunkte |
| --- | --- | --- |
| CLI | interaktive Nutzung, lokales Routing, Shell-Kommandos | `nova_shell.py`, `NovaShell`, `ShellCommandReference` |
| Engines | lokale Compute- und Datenausfuehrung | `py`, `cpp`, `gpu`, `wasm`, `data`, `sys` |
| Sprache | deklarative Beschreibung von Ressourcen, Flows und Systemzustand | `NovaParser`, `NovaAST`, `.ns`-Dateien |
| Graph Engine | AST-zu-DAG-Kompilation | `NovaGraphCompiler`, `ExecutionGraph` |
| Runtime | Laden, Kompilieren, Ausfuehren, Events, Snapshots | `NovaRuntime`, `RuntimeContext` |
| Agents | modellgestuetzte Aufgaben mit Tools, Memory und Governance | `AgentRuntime`, `AgentSpecification`, `AgentTask` |
| Memory und Knowledge | lokales Wissen, Suche, Sharding, Embeddings | `Atheria`, `DistributedMemoryStore`, `NovaVectorMemory` |
| Mesh | verteilte Worker, Dispatch, Capabilities, Remote-Ausfuehrung | `MeshRegistry`, `WorkerNode`, `MeshWorkerServer` |
| Control Plane | Queue, Schedules, Replay, API, Status | `DurableControlPlane`, `NovaControlPlaneAPIServer` |
| Service Fabric | Services, Packages, Revisionen, Traffic | `ServiceFabric`, `ServiceTrafficPlane` |
| Security | Rollen, Namespaces, Secrets, TLS, Trust | `SecurityPlane`, `RuntimePolicy` |

## Wie die Schichten zusammenwirken

```text
CLI oder .ns-Datei
  ->
Parser und AST
  ->
Graph Compiler
  ->
Runtime
  ->
Tools / Agents / Memory / Mesh / Services
  ->
Status, Events, API, Traces
```

## Betriebsmodi

Nova-shell kann in mehreren Modi benutzt werden:

- als interaktive Compute- und AI-Shell
- als deklarative `.ns`-Runtime
- als lokale Agent- und Knowledge-Laufzeit
- als verteilte Worker- und Mesh-Plattform
- als Service- und Traffic-Steuerungsschicht
- als API- und Control-Plane-Prozess

## Typische Daten- und Kontrollfluesse

### Datenfluss

```text
Dataset -> Tool -> Agent -> Memory -> Result
```

### Kontrollfluss

```text
Event -> Flow -> Graph -> Node Execution -> Event / State / Service Action
```

## Testbare Einstiege

### Installations- und Systemfaehigkeiten pruefen

```powershell
doctor
```

### Deklarativen Graph ansehen

```powershell
ns.graph examples\market_radar.ns
```

### Runtime- und Plattformstatus ansehen

```powershell
ns.status
ns.control
```

## Wichtige Startpunkte im Code

- `nova_shell.py`
- `nova/parser/parser.py`
- `nova/graph/compiler.py`
- `nova/runtime/runtime.py`
- `nova/runtime/api.py`
- `nova/agents/runtime.py`
- `nova/mesh/registry.py`

## Typische Fragen

### Ist Nova-shell nur eine Shell?

Nein. Die Shell ist nur eine Schicht. Darunter liegen Sprache, Graph, Runtime, Agenten, Mesh und Plattformdienste.

### Wo beginne ich, wenn ich einen Fehler suche?

Zuerst:

1. `doctor`
2. `ns.status`
3. die passende Fachseite der betroffenen Schicht

### Wo beginne ich, wenn ich entwickeln will?

Mit [DevelopmentGuide](./DevelopmentGuide.md), [RepositoryStructure](./RepositoryStructure.md) und der passenden Referenzseite.

## Verwandte Seiten

- [Architecture](./Architecture.md)
- [ComponentModel](./ComponentModel.md)
- [NovaRuntime](./NovaRuntime.md)
- [Subsystems](./Subsystems.md)
- [ClassReference](./ClassReference.md)

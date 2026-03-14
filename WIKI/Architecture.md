# Architecture

## Gesamtbild

Nova-shell ist eine Plattform mit drei gekoppelten Ebenen:

1. interaktive CLI und Shell
2. deklarative Nova Language fuer `.ns`-Programme
3. AI-OS-Runtime fuer verteilte und agentische Systeme

## Oberbau

```text
User
  ↓
CLI / Nova Language
  ↓
Parser / Toolchain / Graph Compiler
  ↓
Runtime
  ├── Execution Engines
  ├── Agents and Memory
  ├── Event and Workflow Plane
  ├── Control Plane
  ├── Service Fabric
  ├── Traffic Plane
  ├── Security
  └── Operations
```

## Architekturprinzipien

- minimale, komponierbare Bedienung
- deklarative Systembeschreibung
- graphbasierte Ausfuehrung
- agent-native Workflows
- eventgetriebene Orchestrierung
- modulare Backends

## Weiterfuehrend

- [SystemOverview](./SystemOverview.md)
- [ComponentModel](./ComponentModel.md)
- [ExecutionModel](./ExecutionModel.md)
- [DataFlow](./DataFlow.md)

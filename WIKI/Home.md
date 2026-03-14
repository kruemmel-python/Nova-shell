# Nova-shell

## Projektbeschreibung

Nova-shell ist eine polyglotte Runtime-Plattform fuer Compute, AI, Workflows, Events, Wissensspeicher und verteilte Ausfuehrung.

Das System verbindet:

- eine interaktive Shell
- eine deklarative Sprache fuer `.ns`-Programme
- eine AI-OS-Laufzeit mit Control Plane, Mesh, Service-Fabric und Toolchain

## Kernideen

- einheitliche Bedienung fuer lokale und verteilte Ausfuehrung
- graphbasierte Orchestrierung statt rein linearer Skripte
- agent-native Workflows
- eventgetriebene Runtime
- integrierte Sicherheit, Observability und Betriebsfunktionen

## Hauptfeatures

- CLI fuer Python, C++, GPU, WASM, AI und Services
- Nova Language fuer Agenten, Flows, Events, Services und Packages
- Runtime mit Queue, Scheduler, API, Replay und Snapshot
- Agenten mit Prompt-Versionen, Provider-Adaptern, Memory und Evals
- Mesh-Worker und standardisierte Executor-Protokolle
- Service-Fabric mit Routing, Health-Probes und Traffic-Shifts
- Toolchain mit Imports, Lockfiles, Formatter, Linter, LSP und `.ns`-Tests

## Schnellstart

- [QuickStart](./QuickStart.md)
- [Installation](./Installation.md)
- [NovaCLI](./NovaCLI.md)

## Architektur

- [Architecture](./Architecture.md)
- [ExecutionModel](./ExecutionModel.md)
- [DataFlow](./DataFlow.md)

## Entwicklung und Betrieb

- [DevelopmentGuide](./DevelopmentGuide.md)
- [SecurityModel](./SecurityModel.md)
- [Troubleshooting](./Troubleshooting.md)

# Nova-shell Wiki

Nova-shell ist eine kombinierte Shell-, Runtime- und AI-OS-Plattform.
Die Wiki soll deshalb nicht nur Fragen beantworten, sondern das System in drei Tiefen dokumentieren:

1. Nutzung
2. Architektur
3. Referenz

## Was Nova-shell ist

Nova-shell verbindet:

- eine interaktive CLI fuer Compute, AI, Events, Memory und Services
- eine deklarative Sprache fuer `.ns`-Programme
- eine Runtime mit Graph-Ausfuehrung, Agenten, Atheria, Mesh und Control Plane

Im Projekt existieren zwei Laufzeitpfade:

- `nova_shell.py` fuer die bestehende Shell- und Befehlsruntime
- `nova/` fuer Parser, Graph-Compiler, deklarative Runtime, Agents, Events, Mesh und Toolchain

## Wie diese Wiki gelesen werden sollte

Wenn du neu im Projekt bist:

- [QuickStart](./QuickStart.md)
- [Installation](./Installation.md)
- [NovaCLI](./NovaCLI.md)
- [ExamplesAndRecipes](./ExamplesAndRecipes.md)

Wenn du die Architektur verstehen willst:

- [Architecture](./Architecture.md)
- [SystemOverview](./SystemOverview.md)
- [ComponentModel](./ComponentModel.md)
- [NovaLanguage](./NovaLanguage.md)
- [NovaRuntime](./NovaRuntime.md)
- [NovaAgents](./NovaAgents.md)
- [NovaMesh](./NovaMesh.md)

Wenn du Klassen, Methoden, Endpunkte und Einstiegspunkte suchst:

- [ClassReference](./ClassReference.md)
- [ParserAndASTReference](./ParserAndASTReference.md)
- [RuntimeMethodReference](./RuntimeMethodReference.md)
- [APIReference](./APIReference.md)

## Dokumentationsbereiche

### Einstieg

- [QuickStart](./QuickStart.md): erster produktiver Lauf
- [Installation](./Installation.md): Setup und Voraussetzungen
- [Troubleshooting](./Troubleshooting.md): typische Probleme

### Nutzung

- [NovaCLI](./NovaCLI.md): Kommandogruppen, Syntax und typische Aufrufe
- [APIReference](./APIReference.md): HTTP-Control-Plane-API mit Beispielen
- [Tutorials](./Tutorials.md): gefuehrte Workflows
- [ExamplesAndRecipes](./ExamplesAndRecipes.md): kurze, konkrete Anwendungsrezepte

### Architektur

- [Architecture](./Architecture.md): Gesamtarchitektur
- [SystemOverview](./SystemOverview.md): Subsysteme, Rollen und Betriebsmodi
- [ComponentModel](./ComponentModel.md): deklarative Bausteine und Graph-Knoten
- [ExecutionModel](./ExecutionModel.md): Laufzeitfluss
- [DataFlow](./DataFlow.md): Daten- und Event-Pfade

### Sprach- und Toolchain-Schicht

- [NovaLanguage](./NovaLanguage.md): Syntax, Deklarationen und Beispiele
- [ParserAndASTReference](./ParserAndASTReference.md): Parser- und AST-Klassen
- [ToolchainAndTesting](./ToolchainAndTesting.md): Formatter, Linter, LSP und `.ns`-Tests

### Laufzeit- und Plattformschicht

- [NovaRuntime](./NovaRuntime.md): Runtime-Lebenszyklus und Plattformdienste
- [NovaAgents](./NovaAgents.md): Agent-Laufzeit, Governance, Memory und Evals
- [NovaMesh](./NovaMesh.md): Worker, Protokolle und verteilte Ausfuehrung
- [ServiceFabricAndTrafficPlane](./ServiceFabricAndTrafficPlane.md): Services, Routing, Probes und Traffic-Shifts
- [OperationsAndObservability](./OperationsAndObservability.md): Traces, Alerts, Backups, Recovery

### Referenz

- [ClassReference](./ClassReference.md): wichtigste Klassen nach Modul gruppiert
- [RuntimeMethodReference](./RuntimeMethodReference.md): zentrale `NovaRuntime`-Methoden
- [APIReference](./APIReference.md): Endpunkte mit Zweck und Beispielnutzung
- [RepositoryStructure](./RepositoryStructure.md): Verzeichnisstruktur

## Typische Lesepfade

### Fuer Anwender

1. [QuickStart](./QuickStart.md)
2. [NovaCLI](./NovaCLI.md)
3. [ExamplesAndRecipes](./ExamplesAndRecipes.md)

### Fuer Sprach- und Runtime-Entwickler

1. [NovaLanguage](./NovaLanguage.md)
2. [ParserAndASTReference](./ParserAndASTReference.md)
3. [NovaRuntime](./NovaRuntime.md)
4. [RuntimeMethodReference](./RuntimeMethodReference.md)

### Fuer Plattform- und Infrastrukturarbeit

1. [SystemOverview](./SystemOverview.md)
2. [NovaMesh](./NovaMesh.md)
3. [APIReference](./APIReference.md)
4. [OperationsAndObservability](./OperationsAndObservability.md)

## Leitgedanke dieser Wiki

Diese Wiki ist keine reine FAQ.
Sie soll drei Dinge gleichzeitig leisten:

- Orientierung fuer Nutzer
- Architekturverstaendnis fuer Entwickler
- Referenz fuer Klassen, Funktionen, Endpunkte und Beispiele

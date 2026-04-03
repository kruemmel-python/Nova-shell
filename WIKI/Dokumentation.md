# Dokumentation

## Zweck
Diese Seite ist die wiki-native Fassung der zentralen Nova-shell-Gesamtdokumentation.
Sie dient als Einstiegspunkt fuer Leser, die nicht zuerst einzelne Spezialseiten oeffnen wollen, sondern einen geordneten Gesamtueberblick ueber:

- die Hauptschichten von Nova-shell
- die wichtigsten Kommandofamilien
- die aktuell produktivsten Einstiege
- die passenden Referenzseiten in der Wiki

## Nova-shell in einer Kurzformel
Nova-shell ist heute eine kombinierte Plattform aus:

1. interaktiver Shell und polyglotter Runtime
2. deklarativer Sprache fuer `.ns`
3. AI-, Knowledge- und Control-Plane-Schicht

Die Plattform verbindet:

- Python, C++, GPU, WASM und externe Tools
- Agenten, Atheria, Memory und Tool-Nutzung
- Watch-, Event- und Flow-Logik
- Mesh, Remote-Dispatch und Service-Fabric
- HTML-Wiki, Reports, Release und Nachvollziehbarkeit

## Wofuer diese Seite gedacht ist
Diese Seite ist besonders sinnvoll, wenn du:

- schnell verstehen willst, welche Teile Nova-shell heute wirklich umfasst
- einen kompakten Ueberblick ueber die Kommandofamilien brauchst
- entscheiden willst, mit welcher Wiki-Seite du als Naechstes weitermachen solltest

Sie ersetzt nicht die Fachseiten, sondern ordnet sie.

## Die Hauptschichten

### Shell und Runtime
Der erste Einstiegspunkt ist die interaktive Nova-shell selbst. Dort laufen direkte Kommandos, Pipelines und lokale Workflows.

Wichtige Seiten:

- [NovaCLI](./NovaCLI.md)
- [ShellCommandReference](./ShellCommandReference.md)
- [ProgrammingWithNovaShell](./ProgrammingWithNovaShell.md)

### Nova Language
Mit `.ns` beschreibt Nova-shell nicht nur Befehlsfolgen, sondern Systeme, Agenten, Datensaetze, Events, Services und Flows als Graph.

Wichtige Seiten:

- [NovaLanguage](./NovaLanguage.md)
- [nsCreate](./nsCreate.md)
- [nsReference](./nsReference.md)
- [nsPatterns](./nsPatterns.md)
- [examples_index](./examples_index.md)
- [examples](./examples.md)

### AI, Atheria und Memory
Nova-shell enthaelt eine produktive Wissens- und Agentenschicht. Dazu gehoeren Agenten, Tool-Aufrufe, Prompt-/Memory-Pfade und Atheria als lokales Wissens- und Trainingssystem.

Wichtige Seiten:

- [NovaAgents](./NovaAgents.md)
- [AgentsAndKnowledge](./AgentsAndKnowledge.md)
- [NovaMemory](./NovaMemory.md)

### Mesh, Runtime und Plattformbetrieb
Nova-shell umfasst inzwischen auch Control-Plane-, Mesh-, Recovery-, Rollout- und Service-Pfade.

Wichtige Seiten:

- [NovaRuntime](./NovaRuntime.md)
- [NovaMesh](./NovaMesh.md)
- [ServiceFabricAndTrafficPlane](./ServiceFabricAndTrafficPlane.md)
- [OperationsAndObservability](./OperationsAndObservability.md)

### Mobilitaet, Optimierung und Spezialpfade
Zu den markanten Plattformpfaden gehoeren Blob-Seeds, Predictive Engine Shifting, Federated Mesh und Co-Evolution.

Wichtige Seiten:

- [NSBlobGenerator](./NSBlobGenerator.md)
- [NovaSynthPredictiveEngineShifting](./NovaSynthPredictiveEngineShifting.md)
- [ZeroCopyFederatedLearningMesh](./ZeroCopyFederatedLearningMesh.md)
- [MyceliaAtheriaCoEvolution](./MyceliaAtheriaCoEvolution.md)

## Die wichtigsten Kommandofamilien

### Basis

- `help`
- `doctor`
- `pwd`
- `cd`
- `sys`

### Compute

- `py`
- `cpp`
- `gpu`
- `wasm`

### AI und Knowledge

- `ai`
- `atheria`
- `agent`
- `memory`
- `tool`
- `mycelia`

### Verteilung und Plattform

- `mesh`
- `remote`
- `vision`
- `wiki`
- `blob`
- `synth`

### Deklarative Runtime

- `ns.exec`
- `ns.run`
- `ns.graph`
- `ns.status`
- `ns.control`
- `ns.snapshot`
- `ns.resume`

## Wo der schnellste praktische Nutzen liegt
Fuer viele Teams sind diese Bereiche heute der direkteste Einstieg mit echtem Mehrwert:

### 0. Example-Portal
Wenn du moeglichst schnell verstehen willst, was die vorhandenen Beispielprogramme im Repository leisten, beginne hier.

Weiterlesen:

- [examples_index](./examples_index.md)
- [examples_quickstart](./examples_quickstart.md)
- [examples_by_level](./examples_by_level.md)
- [examples_matrix](./examples_matrix.md)

### 1. Watch Monitor
Projektordner beobachten, Diffs und Hotspots anzeigen, HTML-Berichte erzeugen und optional Build/Test/AI-Review ausloesen.

Weiterlesen:

- [WatchMonitor](./WatchMonitor.md)
- [WatchMonitorQuickStart](./WatchMonitorQuickStart.md)
- [WatchMonitorAutomationAndAI](./WatchMonitorAutomationAndAI.md)

### 2. HTML-Wiki
Projektwissen und technische Dokumentation lokal als HTML-Wiki bauen und direkt bereitstellen.

Weiterlesen:

- [Home](./Home.md)
- [NovaCLI](./NovaCLI.md)

### 3. Atheria und Agenten
Lokales Wissen, Training, Suche und Agentenabläufe in derselben Plattform zusammenfuehren.

Weiterlesen:

- [NovaAgents](./NovaAgents.md)
- [AgentsAndKnowledge](./AgentsAndKnowledge.md)
- [NovaMemory](./NovaMemory.md)

### 4. `.ns`-Programme
Wiederkehrende Abläufe nicht nur skripten, sondern deklarativ und graphbasiert beschreiben.

Weiterlesen:

- [nsCreate](./nsCreate.md)
- [nsReference](./nsReference.md)
- [nsPatterns](./nsPatterns.md)
- [examples](./examples.md)
- [examples_quickstart](./examples_quickstart.md)

## Empfohlene Lesepfade

### Fuer neue Nutzer

1. [Home](./Home.md)
2. [QuickStart](./QuickStart.md)
3. [Dokumentation](./Dokumentation.md)
4. [examples_index](./examples_index.md)
5. [examples_quickstart](./examples_quickstart.md)
6. [NovaCLI](./NovaCLI.md)
7. [ExamplesAndRecipes](./ExamplesAndRecipes.md)

### Fuer technische Leiter und Architekten

1. [Was-es-Ist](./Was-es-Ist.md)
2. [Whitepaper](./Whitepaper.md)
3. [wirtschaftlicher_nutzen](./wirtschaftlicher_nutzen.md)
4. [SystemOverview](./SystemOverview.md)
5. [NovaRuntime](./NovaRuntime.md)

### Fuer Runtime- und Sprachentwickler

1. [NovaLanguage](./NovaLanguage.md)
2. [nsCreate](./nsCreate.md)
3. [ParserAndASTReference](./ParserAndASTReference.md)
4. [RuntimeMethodReference](./RuntimeMethodReference.md)
5. [CodeReferenceIndex](./CodeReferenceIndex.md)

## Verwandte Seiten

- [Home](./Home.md)
- [README](./README.md)
- [examples_index](./examples_index.md)
- [examples](./examples.md)
- [examples_quickstart](./examples_quickstart.md)
- [examples_by_level](./examples_by_level.md)
- [examples_matrix](./examples_matrix.md)
- [Was-es-Ist](./Was-es-Ist.md)
- [Whitepaper](./Whitepaper.md)
- [wirtschaftlicher_nutzen](./wirtschaftlicher_nutzen.md)
- [NovaCLI](./NovaCLI.md)
- [NovaRuntime](./NovaRuntime.md)

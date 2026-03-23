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
- [Dokumentation](./Dokumentation.md)
- [ProgrammingWithNovaShell](./ProgrammingWithNovaShell.md)
- [nsCreate](./nsCreate.md)
- [nsReference](./nsReference.md)
- [nsPatterns](./nsPatterns.md)
- [NovaDecisionSystem](./NovaDecisionSystem.md)
- [NovaSemantics](./NovaSemantics.md)
- [NovaCLI](./NovaCLI.md)
- [ExamplesAndRecipes](./ExamplesAndRecipes.md)
- [DecisionPatterns](./DecisionPatterns.md)
- [CEOAgentExamples](./CEOAgentExamples.md)
- [StandaloneSkillAgents](./StandaloneSkillAgents.md)
- [StandaloneSkillAgentsForDevelopers](./StandaloneSkillAgentsForDevelopers.md)
- [TutorialStandaloneSkillAgents](./TutorialStandaloneSkillAgents.md)

Wenn du die Architektur verstehen willst:

- [Architecture](./Architecture.md)
- [SystemOverview](./SystemOverview.md)
- [ComponentModel](./ComponentModel.md)
- [NovaLanguage](./NovaLanguage.md)
- [NovaRuntime](./NovaRuntime.md)
- [NovaDecisionSystem](./NovaDecisionSystem.md)
- [NovaSemantics](./NovaSemantics.md)
- [DecisionPatterns](./DecisionPatterns.md)
- [NovaLens](./NovaLens.md)
- [NovaAgents](./NovaAgents.md)
- [NovaMesh](./NovaMesh.md)
- [NSBlobGenerator](./NSBlobGenerator.md)
- [NovaSynthPredictiveEngineShifting](./NovaSynthPredictiveEngineShifting.md)
- [ZeroCopyFederatedLearningMesh](./ZeroCopyFederatedLearningMesh.md)
- [MyceliaAtheriaCoEvolution](./MyceliaAtheriaCoEvolution.md)
- [AtheriaContinuousEvolutionAndLiveStream](./AtheriaContinuousEvolutionAndLiveStream.md)
- [AtheriaVoice](./AtheriaVoice.md)
- [AtheriaALSForDevelopers](./AtheriaALSForDevelopers.md)

Wenn du Klassen, Methoden, Endpunkte und Einstiegspunkte suchst:

- [ClassReference](./ClassReference.md)
- [CodeReferenceIndex](./CodeReferenceIndex.md)
- [ShellCommandReference](./ShellCommandReference.md)
- [NovaLens](./NovaLens.md)
- [LensForDevelopers](./LensForDevelopers.md)
- [LensTroubleshooting](./LensTroubleshooting.md)
- [LensRecipes](./LensRecipes.md)
- [ParserAndASTReference](./ParserAndASTReference.md)
- [RuntimeMethodReference](./RuntimeMethodReference.md)
- [APIReference](./APIReference.md)

## Dokumentationsbereiche

### Einstieg

- [QuickStart](./QuickStart.md): erster produktiver Lauf
- [Installation](./Installation.md): Setup und Voraussetzungen
- [Dokumentation](./Dokumentation.md): zentrale Gesamt- und Kommandoreferenz als Wiki-Seite
- [Troubleshooting](./Troubleshooting.md): typische Probleme

### Nutzung

- [NovaCLI](./NovaCLI.md): Kommandogruppen, Syntax und typische Aufrufe
- [ProgrammingWithNovaShell](./ProgrammingWithNovaShell.md): wie man mit CLI, `.ns` und Python wirklich programmiert
- [ShellCommandReference](./ShellCommandReference.md): Zuordnung von Kommandos zu Handlern
- [NovaLens](./NovaLens.md): Lens-Snapshots, `lineage.db` und effizienter CAS-Speicher fuer Shell- und Monitor-Laeufe
- [LensForDevelopers](./LensForDevelopers.md): SQLite-Schema, CAS-Lookup und Debug-Rezepte fuer Lens
- [LensTroubleshooting](./LensTroubleshooting.md): kaputte CAS-Referenzen, leerer Replay und Cleanup-/Reset-Regeln
- [LensRecipes](./LensRecipes.md): Copy-Paste-Rezepte fuer Lookup, Replay, CAS-Zuordnung und sicheren Reset
- [APIReference](./APIReference.md): HTTP-Control-Plane-API mit Beispielen
- [NSBlobGenerator](./NSBlobGenerator.md): verifizierbare Seed-Kapselung, Rehydrierung und mobiler Mesh-Transport
- [NovaSynthPredictiveEngineShifting](./NovaSynthPredictiveEngineShifting.md): forecast-basierte Umschaltung zwischen `py`, `cpp`, `gpu` und `mesh`
- [ZeroCopyFederatedLearningMesh](./ZeroCopyFederatedLearningMesh.md): signierte Invariant-Synchronisation und same-host zero-copy im Mesh
- [MyceliaAtheriaCoEvolution](./MyceliaAtheriaCoEvolution.md): populationsbasierte Optimierung mit Forecast-, Invariant- und Kruemmungssignalen
- [AtheriaContinuousEvolutionAndLiveStream](./AtheriaContinuousEvolutionAndLiveStream.md): residenter Live-Stream-Pfad fuer Atheria mit Chronik, Lens, Triggern und Dialog
- [AtheriaVoice](./AtheriaVoice.md): Speech Acts, Prosodie und lokale Audioausgabe als Teil der Atheria-Kognition
- [AtheriaALSForDevelopers](./AtheriaALSForDevelopers.md): Dateilayout, Lebenszyklus, Triggerlogik und Erweiterungspunkte fuer ALS
- [WatchMonitor](./WatchMonitor.md): Projektordner live ueberwachen, analysieren und HTML-Reports aktualisieren
- [SystemGuardMonitor](./SystemGuardMonitor.md): kritische Windows-Pfade fuer Persistenz, Temp-Ausfuehrung und Host-Integrity ueberwachen
- [TutorialProjectWatchMonitor](./TutorialProjectWatchMonitor.md): Schritt-fuer-Schritt-Aufbau eines echten Projektwaechters
- [TutorialBlobSeeds](./TutorialBlobSeeds.md): Blob-Seeds bauen, verifizieren, ausfuehren und ueber Mesh verschieben
- [TutorialPredictiveFederatedCoevolution](./TutorialPredictiveFederatedCoevolution.md): Forecast, Federated Mesh und Co-Evolution als zusammenhaengender Plattformpfad
- [TutorialAtheriaALS](./TutorialAtheriaALS.md): residentes ALS aufsetzen, befragen, mit Voice betreiben und wieder stoppen
- [Tutorials](./Tutorials.md): gefuehrte Workflows
- [ExamplesAndRecipes](./ExamplesAndRecipes.md): kurze, konkrete Anwendungsrezepte
- [NovaDecisionSystem](./NovaDecisionSystem.md): formale Definition eines Decision Systems als deklarativer, graphbasierter Laufzeitpfad
- [DecisionPatterns](./DecisionPatterns.md): formale Muster fuer Bundle-, Flow-, Lifecycle- und Entscheidungsarchitekturen
- [CEOAgentExamples](./CEOAgentExamples.md): modulare CEO-Agenten als einzelne Bundles und als zusammenhaengender Lifecycle
- [StandaloneSkillAgents](./StandaloneSkillAgents.md): eigenstaendige `.ns`-Agenten aus lokalen Skill-Daten erzeugen und ohne Quellordner weiterverwenden
- [StandaloneSkillAgentsForDevelopers](./StandaloneSkillAgentsForDevelopers.md): Generatorarchitektur, Portabilitaetsregeln und Debugging fuer Skill-Agenten
- [TutorialStandaloneSkillAgents](./TutorialStandaloneSkillAgents.md): Schritt-fuer-Schritt vom Skill-Quellordner bis zum nutzbaren `agent run`

### Architektur

- [Architecture](./Architecture.md): Gesamtarchitektur
- [SystemOverview](./SystemOverview.md): Subsysteme, Rollen und Betriebsmodi
- [ComponentModel](./ComponentModel.md): deklarative Bausteine und Graph-Knoten
- [ExecutionModel](./ExecutionModel.md): Laufzeitfluss
- [DataFlow](./DataFlow.md): Daten- und Event-Pfade

### Sprach- und Toolchain-Schicht

- [NovaLanguage](./NovaLanguage.md): Syntax, Deklarationen und Beispiele
- [nsCreate](./nsCreate.md): ausfuehrlicher Schreibleitfaden fuer echte `.ns`-Programme
- [nsReference](./nsReference.md): kompakte Sprachreferenz fuer alle Bausteine und Felder
- [nsPatterns](./nsPatterns.md): gute und schlechte Muster fuer wachsende `.ns`-Programme
- [ParserAndASTReference](./ParserAndASTReference.md): Parser- und AST-Klassen
- [ToolchainAndTesting](./ToolchainAndTesting.md): Formatter, Linter, LSP und `.ns`-Tests

### Laufzeit- und Plattformschicht

- [NovaRuntime](./NovaRuntime.md): Runtime-Lebenszyklus und Plattformdienste
- [NovaLens](./NovaLens.md): persistente Shell-Lineage, Replay und content-addressable Speicherung
- [NovaAgents](./NovaAgents.md): Agent-Laufzeit, Governance, Memory und Evals
- [NovaMesh](./NovaMesh.md): Worker, Protokolle und verteilte Ausfuehrung
- [NSBlobGenerator](./NSBlobGenerator.md): mobile Logik-Seeds fuer CLI, Runtime und Mesh
- [NovaSynthPredictiveEngineShifting](./NovaSynthPredictiveEngineShifting.md): Forecast-gesteuerte Engine-Migration
- [ZeroCopyFederatedLearningMesh](./ZeroCopyFederatedLearningMesh.md): Schwarmgedaechtnis und verifizierte Invariant-Verteilung
- [MyceliaAtheriaCoEvolution](./MyceliaAtheriaCoEvolution.md): genetische Optimierung ueber Atheria-Signale
- [AtheriaContinuousEvolutionAndLiveStream](./AtheriaContinuousEvolutionAndLiveStream.md): residenter Atheria-Live-Loop mit Triggern, Chronik und Speech Acts
- [AtheriaVoice](./AtheriaVoice.md): Voice als Grundschicht der Atheria-Ausgabe
- [AtheriaALSForDevelopers](./AtheriaALSForDevelopers.md): Entwicklerblick auf ALS-Zustand, Dateilayout und Erweiterungspunkte
- [ServiceFabricAndTrafficPlane](./ServiceFabricAndTrafficPlane.md): Services, Routing, Probes und Traffic-Shifts
- [OperationsAndObservability](./OperationsAndObservability.md): Traces, Alerts, Backups, Recovery
- [WatchMonitorReportReference](./WatchMonitorReportReference.md): HTML-Report, JSON-Dateien, Detailseiten und Hotspots
- [SystemGuardMonitor](./SystemGuardMonitor.md): zweiter Watch-Pfad fuer Host-Integrity statt Repo-Churn

### Referenz

- [ClassReference](./ClassReference.md): wichtigste Klassen nach Modul gruppiert
- [CodeReferenceIndex](./CodeReferenceIndex.md): vollstaendiger Symbolindex von Modulen, Klassen und Methoden
- [ShellCommandReference](./ShellCommandReference.md): Shell-Router, Handler und Kommandofamilien
- [NovaLens](./NovaLens.md): Shell-Lineage, CAS und Replay ueber reale Laufzeitstufen
- [LensForDevelopers](./LensForDevelopers.md): Low-Level-Sicht auf `lineage.db`, `cas/` und Debugging
- [LensTroubleshooting](./LensTroubleshooting.md): Diagnosepfade fuer fehlende Hash-Dateien und inkonsistente Lens-Zustaende
- [LensRecipes](./LensRecipes.md): schnelle Entwickler-Rezepte fuer den taeglichen Lens-Einsatz
- [RuntimeMethodReference](./RuntimeMethodReference.md): zentrale `NovaRuntime`-Methoden
- [APIReference](./APIReference.md): Endpunkte mit Zweck und Beispielnutzung
- [RepositoryStructure](./RepositoryStructure.md): Verzeichnisstruktur

### Strategie und Nutzen

- [wirtschaftlicher_nutzen](./wirtschaftlicher_nutzen.md): wirtschaftliche Einsatzgebiete, ROI-Hebel und realistische Einfuehrungsszenarien
- [Whitepaper](./Whitepaper.md): technische Einordnung und Plattformbild
- [Was-es-Ist](./Was-es-Ist.md): kompakte Projektpositionierung

## Typische Lesepfade

### Fuer Anwender

1. [QuickStart](./QuickStart.md)
2. [ProgrammingWithNovaShell](./ProgrammingWithNovaShell.md)
3. [NovaCLI](./NovaCLI.md)
4. [ExamplesAndRecipes](./ExamplesAndRecipes.md)
5. [TutorialAtheriaALS](./TutorialAtheriaALS.md)

### Fuer Sprach- und Runtime-Entwickler

1. [NovaLanguage](./NovaLanguage.md)
2. [nsCreate](./nsCreate.md)
3. [nsReference](./nsReference.md)
4. [nsPatterns](./nsPatterns.md)
5. [ParserAndASTReference](./ParserAndASTReference.md)
6. [NovaRuntime](./NovaRuntime.md)
7. [AtheriaContinuousEvolutionAndLiveStream](./AtheriaContinuousEvolutionAndLiveStream.md)
8. [AtheriaVoice](./AtheriaVoice.md)
9. [AtheriaALSForDevelopers](./AtheriaALSForDevelopers.md)
10. [NovaLens](./NovaLens.md)
11. [LensForDevelopers](./LensForDevelopers.md)
12. [LensTroubleshooting](./LensTroubleshooting.md)
13. [LensRecipes](./LensRecipes.md)
14. [RuntimeMethodReference](./RuntimeMethodReference.md)
15. [CodeReferenceIndex](./CodeReferenceIndex.md)

### Fuer Plattform- und Infrastrukturarbeit

1. [SystemOverview](./SystemOverview.md)
2. [NovaMesh](./NovaMesh.md)
3. [APIReference](./APIReference.md)
4. [AtheriaContinuousEvolutionAndLiveStream](./AtheriaContinuousEvolutionAndLiveStream.md)
5. [OperationsAndObservability](./OperationsAndObservability.md)

### Fuer Strategie, Einfuehrung und Positionierung

1. [wirtschaftlicher_nutzen](./wirtschaftlicher_nutzen.md)
2. [Whitepaper](./Whitepaper.md)
3. [Was-es-Ist](./Was-es-Ist.md)

## Leitgedanke dieser Wiki

Diese Wiki ist keine reine FAQ.
Sie soll drei Dinge gleichzeitig leisten:

- Orientierung fuer Nutzer
- Architekturverstaendnis fuer Entwickler
- Referenz fuer Klassen, Funktionen, Endpunkte und Beispiele
- einen echten Programmierpfad fuer CLI, `.ns` und Python

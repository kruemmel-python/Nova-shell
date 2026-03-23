# CEO Agent Examples

## Zweck

Diese Seite beschreibt den Ordner `examples/CEO_ns`.

Dort liegt keine Management-Simulation als Black Box, sondern eine kleine,
modulare Beispielstrecke fuer ein CEO-orientiertes Agentensystem in echter
Nova-shell-` .ns`-Syntax.

Die Dateien zeigen zwei Nutzungsarten:

- einzelne Rollen als eigenstaendige Agent-Bundles
- einen zusammenhaengenden Lifecycle als vollstaendigen `flow`

## Explizite Muster in diesem Ordner

Der Ordner ist nicht nur ein Beispiel, sondern zeigt jetzt drei formale Muster:

- `Agent Bundle Pattern`
- `Flow Pattern`
- `Lifecycle Pattern`

Diese Begriffe sind bewusst explizit gemacht, damit das Beispiel nicht nur
ausfuehrbar, sondern auch als Architekturvorlage lesbar wird.

### Agent Bundle Pattern

Die Einzeldateien wie `StrategyAgent.ns` oder `RiskAgent.ns` sind Agent-Bundles:

- eine Datei
- ein klarer Rollenfokus
- nach `ns.run` direkt per `agent run` nutzbar

Das ist sinnvoll fuer:

- Fachrollen
- Router
- Spezialagenten
- modulare Tests

### Flow Pattern

`CEO_Lifecycle.ns` enthaelt einen expliziten Ablauf mit benannten Zwischenstufen:

- `executive_snapshot`
- `strategy_raw`
- `risk_raw`
- `capital_raw`
- `consensus_packet`
- `final_decision`
- `board_message`
- `execution_plan`

Damit bleibt die Kette nicht implizit, sondern im Graph und im Runtime-Output nachvollziehbar.

### Lifecycle Pattern

Das CEO-Beispiel endet nicht bei einer Analyse, sondern schreibt Zustand und emittiert ein Event:

- `state.set ceo_last_execution execution_plan`
- `event.emit ceo_cycle_ready execution_plan`

Genau dadurch wird aus einem Flow ein Lifecycle-Muster.

## Das abstrahierte Decision Pattern

Der CEO-Lifecycle ist eigentlich ein allgemeines Entscheidungsmodell:

```text
input -> transform -> merge -> decide -> act
```

Im CEO-Beispiel ist das:

- `input`: `executive_signals`
- `transform`: `StrategyAgent`, `RiskAgent`, `CapitalAgent`
- `merge`: `ConsensusLayer`
- `decide`: `final_decision`
- `act`: `ExecutionDispatcher`

Dieses Muster laesst sich spaeter auf andere Domaenen uebertragen, etwa:

- Security-Systeme
- Trading-Systeme
- AI-Orchestratoren

Die generalisierte Doku dazu steht auf:

- [NovaDecisionSystem](./NovaDecisionSystem.md)
- [DecisionPatterns](./DecisionPatterns.md)

## Enthaltene Dateien

Der Ordner enthaelt:

- `examples/CEO_ns/CEO_Core.ns`
- `examples/CEO_ns/StrategyAgent.ns`
- `examples/CEO_ns/RiskAgent.ns`
- `examples/CEO_ns/CapitalAgent.ns`
- `examples/CEO_ns/ConsensusLayer.ns`
- `examples/CEO_ns/NarrativeAgent.ns`
- `examples/CEO_ns/ExecutionDispatcher.ns`
- `examples/CEO_ns/CEO_Lifecycle.ns`

## Was diese Dateien tun

### Einzelne Agenten

Die Einzeldateien sind kompakte `agent bundle`-Programme.
Sie werden mit `ns.run` geladen und exportieren danach genau einen Agenten in die Shell.

Rollen:

- `CEO_Core`: Router fuer die passende naechste Rolle
- `StrategyAgent`: strategischer Vorschlag
- `RiskAgent`: Risiko- und Warnsignalbewertung
- `CapitalAgent`: Kapitalallokation und Liquiditaetsblick
- `ConsensusLayer`: Zusammenfuehrung zu einer Managemententscheidung
- `NarrativeAgent`: Board- und Kommunikationsnarrativ
- `ExecutionDispatcher`: operative Erstmassnahmen

### CEO_Lifecycle

`CEO_Lifecycle.ns` ist die zusammenhaengende Beispielpipeline.

Der Flow:

1. liest Beispielsignale aus einem eingebetteten Dataset
2. erzeugt Strategie-, Risiko- und Kapitalartefakte
3. verdichtet diese in einer Consensus-Entscheidung
4. formuliert daraus ein Board-Narrativ
5. erzeugt einen operativen Dispatch
6. speichert das Ergebnis unter `ceo_last_execution`
7. emittiert das Event `ceo_cycle_ready`

## Warum die Dateien ueberarbeitet wurden

Die urspruengliche Fassung in `examples/CEO_ns` war kein lauffaehiges Nova-Script,
sondern Pseudokonfiguration mit Feldern wie:

- `input:`
- `compute:`
- `output:`
- `emit:`
- `signals:`
- `routes:`
- `loop:`

Diese Form wird von der Nova-shell-Runtime nicht als echte deklarative `.ns`-Sprache verstanden.

Die aktuelle Fassung nutzt stattdessen unterstuetzte Bausteine:

- `system { ... }`
- `state { ... }`
- `agent { ... }`
- `dataset { ... }`
- `flow { ... }`
- `event { ... }`

## Schnellstart

### 1. Einzelnen Agenten laden

Beispiel mit dem Strategy-Agenten:

```powershell
ai use lmstudio <modellname>
ns.run .\examples\CEO_ns\StrategyAgent.ns
agent run StrategyAgent "Pipeline waechst, GPU-Auslastung steigt, ein Channel-Partner fordert Co-Investment."
```

Danach kannst du jeden einzelnen Agenten gezielt befragen.

### 2. Router laden

```powershell
ai use lmstudio <modellname>
ns.run .\examples\CEO_ns\CEO_Core.ns
agent run CEO_Core "Welche Rolle soll eine Entscheidung ueber Kapazitaetsausbau und Co-Investment jetzt zuerst bearbeiten?"
```

### 3. Den gesamten Lifecycle ausfuehren

```powershell
ns.run .\examples\CEO_ns\CEO_Lifecycle.ns
```

Erwartung:

- der Flow `ceo_lifecycle` wird ausgefuehrt
- im Runtime-Status liegt danach `execution_plan`
- ausserdem wird `ceo_last_execution` als State geschrieben

### 4. Den Graph des CEO-Lifecycle rendern

```powershell
ns.graph .\examples\CEO_ns\CEO_Lifecycle.ns
```

Das ist der schnellste Weg, die Struktur visuell zu verstehen:

- Knoten: Rollen, Dataset, Flow, Event und Tool-Schritte
- Kanten: welche Stufe welches Artefakt an die naechste uebergibt

Gerade fuer Reviews und Architekturgespraeche ist das oft verstaendlicher als
der rohe `.ns`-Quelltext.

## Wichtiger Laufzeitunterschied

Die Einzel-Agenten sind fuer interaktive Nutzung mit einem echten generativen Provider gedacht,
typischerweise `LM Studio`.

Deshalb ist fuer diese Dateien der sinnvolle Pfad:

```powershell
ai use lmstudio <modellname>
ns.run .\examples\CEO_ns\RiskAgent.ns
agent run RiskAgent "Die Nachfrage steigt, aber die GPU-Kapazitaet ist fast ausgeschoepft."
```

`CEO_Lifecycle.ns` ist bewusst robuster gebaut:

- die eingebetteten Lifecycle-Agenten verwenden `provider: local`
- dadurch laeuft der Flow auch ohne aktive externe Modellkonfiguration
- der Lifecycle dient damit als jederzeit testbares Strukturbeispiel

Wenn du fuer den Lifecycle selbst echte Modellantworten willst, kannst du die
eingebetteten Agenten spaeter auf `provider: shell` und `model: active` umstellen.

## Typische Kommandos

Agenten nach einem Bundle-Ladevorgang anzeigen:

```powershell
ns.run .\examples\CEO_ns\CapitalAgent.ns
agent list
```

Mit qualifiziertem Namen arbeiten:

```powershell
agent run CapitalAgent.CapitalAgent "Vorschlag benoetigt 1.8 Mio. EUR fuer beschleunigten Ausbau."
```

Lifecycle erneut ueber Event triggern:

```powershell
ns.run .\examples\CEO_ns\CEO_Lifecycle.ns
event emit board.review "quarterly-board-cycle"
```

Runtime-Zustand ansehen:

```powershell
ns.status
```

## Erwartete Ergebnisse

Bei den Einzeldateien liefert `ns.run` ein kompaktes `agent_bundle`-JSON.

Bei `CEO_Lifecycle.ns` liefert `ns.run` ein Flow-Ergebnis mit:

- `flow: ceo_lifecycle`
- `context.outputs.execution_plan`
- `context.states.ceo_last_execution`

## Troubleshooting

### `agent run` liefert keine brauchbare generative Antwort

Dann ist meistens kein generativer Provider aktiv.

Setze vor dem Agentenlauf:

```powershell
ai use lmstudio <modellname>
```

### `CEO_Lifecycle.ns` soll ohne Modell trotzdem laufen

Das ist bereits der Standard.
Der Lifecycle verwendet lokale Fallback-Agenten, damit die Datei auch in Tests,
MSI-Builds und minimalen Laufzeitumgebungen stabil bleibt.

### Ich will nur die Managementlogik verstehen

Dann beginne mit:

- `CEO_Core.ns` fuer Routing
- `ConsensusLayer.ns` fuer die Entscheidungslogik
- `CEO_Lifecycle.ns` fuer das Gesamtbild

## Verwandte Seiten

- [NovaDecisionSystem](./NovaDecisionSystem.md)
- [DecisionPatterns](./DecisionPatterns.md)
- [NovaAgents](./NovaAgents.md)
- [ExamplesAndRecipes](./ExamplesAndRecipes.md)
- [NovaCLI](./NovaCLI.md)
- [nsReference](./nsReference.md)
- [nsPatterns](./nsPatterns.md)

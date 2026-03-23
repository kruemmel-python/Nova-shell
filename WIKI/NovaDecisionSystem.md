# Nova Decision System

## Zweck

Diese Seite definiert formal, was ein `Decision System` in Nova-shell ist.

Ein Decision System ist keine einzelne Agentenrolle, sondern ein
ausfuehrbares, zustandsfaehiges Architekturpattern innerhalb der deklarativen
`.ns`-Runtime.

Es verarbeitet Eingaben, transformiert sie ueber mehrere Perspektiven,
verdichtet diese Perspektiven zu einer Entscheidung und fuehrt daraus eine
operative Folgehandlung ab.

Die Seite abstrahiert konkrete Beispiele wie:

- `examples/CEO_ns/CEO_Lifecycle.ns`
- `examples/decision_lifecycle_template.ns`

## Kerndefinition

Ein Decision System in Nova-shell ist:

> ein deklarativ beschriebenes `.ns`-Programm oder Teilprogramm, das in einen
> gerichteten Ausfuehrungsgraphen kompiliert wird und einen fachlichen Zyklus
> aus Input, Transformation, Verdichtung, Entscheidung und Aktion realisiert

Konzeptionell:

```text
DecisionSystem = Graph(Nodes, Edges, State, Events)
```

mit:

- `Nodes`: Agenten, Datasets, Tools, Flow- und Event-Knoten
- `Edges`: Daten-, Definitions-, Trigger- und Reihenfolgebeziehungen
- `State`: Laufzeit- und Persistenzzustand, sofern der Ablauf ihn nutzt
- `Events`: Trigger und Kopplungspunkte zwischen Flows

Wichtig:

- `Decision System` ist heute kein eigenes Sprach-Keyword
- es ist ein explizites Nova-shell-Architekturpattern
- die technische Grundlage ist der deklarative Graph-Laufzeitpfad

## Das allgemeine Entscheidungsmodell

Das Kernmuster lautet:

```text
input -> transform -> merge -> decide -> act
```

Wenn das System in einen laengerlebigen Runtime-Zyklus eingebunden ist, kommen
haeufig noch zwei weitere Stufen dazu:

```text
input -> transform -> merge -> decide -> act -> state -> event
```

## Mapping auf Nova-Konstrukte

| Phase | Bedeutung | Typische Nova-Konstrukte |
| --- | --- | --- |
| `input` | Eingangssignale oder Eingangsdaten | `dataset`, `event` |
| `transform` | getrennte Perspektiven auf denselben Input | `agent`, `tool`, `py.exec` |
| `merge` | Verdichtung mehrerer Artefakte | `agent`, `tool`, `py.exec` |
| `decide` | finale Urteilsbildung | `agent`, `tool` |
| `act` | operative Folgeaktion | `agent`, `tool`, `event.emit` |
| `state` | persistierte Auswirkung | `state { ... }`, `state.set`, `state.get` |
| `event` | Trigger oder Weitergabe | `event { ... }`, `event.emit` |

Wichtig:

- `system { ... }` gehoert nicht zur Entscheidungsphase selbst
- `system` definiert Laufzeitkontext wie `mode`, `tenant`, `cluster`, `capability`
- die eigentliche Fachlogik sitzt in `flow`, `agent`, `tool`, `dataset`, `state`, `event`

## Minimalstruktur

Ein lauffaehiges Decision System braucht nicht immer alle moeglichen Bausteine,
aber ein belastbares Pattern enthaelt typischerweise:

```text
dataset oder event
flow
mehrere Verarbeitungsstufen
```

Fuer ein voll gekoppeltes, wiederverwendbares Decision System sind zusaetzlich
sehr sinnvoll:

```text
state
event
```

Pragmatisch bedeutet das:

- mindestens eine Inputquelle
- mindestens ein `flow`
- mindestens zwei fachlich verschiedene Verarbeitungsstufen
- `state` und `event`, sobald das System ueber einen einmaligen Lauf hinaus
  sichtbar, triggerbar oder integrierbar sein soll

## Beispiel: CEO-Lifecycle als Instanz

`examples/CEO_ns/CEO_Lifecycle.ns` implementiert dieses Modell explizit.

Fachliche Abbildung:

```text
input:
  executive_signals

transform:
  StrategyAgent
  RiskAgent
  CapitalAgent

merge:
  ConsensusLayer

decide:
  final_decision

act:
  ExecutionDispatcher

state:
  ceo_last_execution

event:
  ceo_cycle_ready
```

Wichtig:

> Der "CEO" ist hier nicht ein einzelner Agent, sondern das Gesamtsystem dieses
> Graphen.

Siehe:

- [CEOAgentExamples](./CEOAgentExamples.md)

## Eigenschaften eines Decision Systems

### 1. Deterministische Struktur

Auch wenn einzelne Agenten generativ oder promptbasiert arbeiten:

- der Graph selbst ist explizit
- die Knoten sind benannt
- die Kanten werden reproduzierbar kompiliert

Die Runtime fuehrt einen Flow ueber die topologische Ordnung des
zugehoerigen Graph-Abschlusses aus.

### 2. Zustandsfaehigkeit

Ein Decision System kann zustandslos entworfen werden, aber in der Praxis wird
es oft durch `state.set` dauerhaft gemacht.

Beispiel:

```text
state.set ceo_last_execution execution_plan
```

Dadurch wird aus einem einmaligen Ablauf ein beobachtbarer Systemzustand.

### 3. Ereignisfaehigkeit

Decision Systems koennen Ergebnisse weiterreichen oder selbst getriggert werden.

Beispiel:

```text
event.emit ceo_cycle_ready execution_plan
```

Dadurch werden sie:

- triggerbar
- koppelfaehig
- in groessere Systeme integrierbar

### 4. Graphbasierte Ausfuehrung

Nova-shell kompiliert deklarative `.ns`-Programme in einen `ExecutionGraph`.

Wichtig ist die Nuance:

- Autoren schreiben Flows meist als lineare Schrittfolge
- die Runtime kompiliert daraus einen DAG-basierten Ausfuehrungsgraphen
- Daten- und Kontrollkanten werden dabei explizit

Deshalb ist die Ausfuehrung nicht nur "ein Skript von oben nach unten", sondern
ein graphisch modellierter Laufzeitpfad.

Siehe auch:

```powershell
ns.graph .\examples\CEO_ns\CEO_Lifecycle.ns
```

### 5. Trennung von Rollen und Struktur

Wichtig:

- Agenten definieren Rollen
- Flows definieren Verhalten
- Datasets definieren Eingaben
- State und Events definieren Kopplung und Dauer

Ein Decision System entsteht erst aus dieser Kombination.

## Abgrenzung zu anderen Systemfamilien

### Gegenueber klassischen Workflow-Systemen

Bei klassischen Workflow- oder DAG-Systemen steht oft primaer die
Aufgabenorchestrierung im Vordergrund.

Nova-shell unterscheidet sich hier durch:

- Agenten als erstklassige Graph-Knoten
- State im selben Programmmodell
- Event-Kopplung im selben deklarativen Pfad
- explizite Entscheidungslogik innerhalb des Flows

Der Punkt ist nicht, dass andere Systeme keine DAGs haben, sondern dass Nova
Entscheidungsrollen und Orchestrierung enger zusammenbindet.

### Gegenueber LLM-Agent-Frameworks

Viele Agent-Frameworks sind prompt- oder sessionzentriert.

Nova-shell kann das ebenfalls, macht aber zusaetzlich die Struktur explizit:

- Rollen koennen als `agent { ... }` deklariert werden
- Entscheidungswege koennen als `flow` modelliert werden
- `ns.graph` macht die Struktur direkt sichtbar

Der Unterschied ist also weniger "LLM vs. kein LLM", sondern:

- implizite Agent-Kette
  vs.
- explizit modellierter Ausfuehrungsgraph

### Gegenueber Infrastruktur-Orchestratoren

Nova-shell hat Plattform- und Service-Bausteine, ist aber nicht einfach ein
Ersatz fuer Kubernetes oder reine Infrastrukturorchestrierung.

Der Schwerpunkt eines Decision Systems in Nova liegt auf:

- Fachentscheidung
- Rollenlogik
- Runtime-Zustand
- Ereigniskopplung

Infrastruktur ist moeglich, aber nicht die alleinige Hauptsache.

## Decision System als wiederverwendbares Muster

Das Modell ist domaenenunabhaengig.

Es eignet sich fuer:

- CEO- und Management-Systeme
- Security-Entscheidungssysteme
- Trading- und Portfolio-Logik
- autonome Infrastruktursteuerung
- AI-Orchestratoren

## Template-Nutzung

Das generische Beispiel:

```text
examples/decision_lifecycle_template.ns
```

stellt eine neutrale Blaupause bereit fuer:

- schnelles Ableiten neuer Systeme
- konsistente Struktur
- `ns.run`- und `ns.graph`-Pruefung
- einfache Testbarkeit

## Testbarkeit

Decision Systems lassen sich auf mehreren Ebenen pruefen:

### Struktur

```powershell
ns.graph <file>.ns
```

### Ausfuehrung

```powershell
ns.run <file>.ns
```

### Automatisierte Regression

Typisch sind Tests fuer:

- Laden
- Graph-Erzeugung
- Flow-Ausfuehrung
- erwartete Outputs
- erwartete State- oder Event-Effekte

## Zentrale Konsequenz

Der Unterschied zu vielen klassischen Skriptpfaden ist:

> In Nova-shell wird nicht nur Code ausgefuehrt, sondern Entscheidungslogik als
> expliziter, testbarer und visualisierbarer Ausfuehrungsgraph modelliert.

## Verwandte Seiten

- [NovaSemantics](./NovaSemantics.md)
- [DecisionPatterns](./DecisionPatterns.md)
- [CEOAgentExamples](./CEOAgentExamples.md)
- [nsPatterns](./nsPatterns.md)
- [NovaRuntime](./NovaRuntime.md)
- [Architecture](./Architecture.md)

# CEO Agent Examples

## Zweck

Diese Seite beschreibt den Ordner `examples/CEO_ns`.

Der Ordner enthaelt inzwischen nicht mehr nur ein loses Agentenbeispiel, sondern
ein kleines CEO-orientiertes Operating System fuer Nova-shell:

- klar getrennte Rollen-Agenten fuer interaktive Arbeit
- ein deterministisches CEO-Decision-System als `.ns`-Flow
- eine kontinuierliche Laufzeit fuer wiederholte CEO-Zyklen
- persistente Reports und Statusartefakte

Wichtig:

> Der eigentliche "CEO" ist hier nicht ein einzelner Agent, sondern das
> zusammengesetzte Decision System aus Signalen, Governance, gewichteter
> Entscheidungslogik, Execution und Feedback.

## Was jetzt real implementiert ist

Der aktuelle Stand deckt die wesentlichen Bausteine eines operativen
Steuerungssystems ab:

- `Domain Model`
- `Signal-System`
- `Strategy`, `Risk`, `Capital`, `Operations`
- `Consensus` mit gewichteter Entscheidung
- `Execution`
- `Memory` und `Feedback`
- `Governance / Policy`
- `Continuous Operation`

Das ist kein Chatbot und auch kein reines Vorschlagssystem.
Der Lifecycle verarbeitet strukturierte Eingaben, trifft eine regelgebundene
Entscheidung und schreibt daraus verbindliche Runtime-Artefakte.

## Explizite Muster in diesem Ordner

Der Ordner zeigt weiterhin drei Architekturpattern:

- `Agent Bundle Pattern`
- `Flow Pattern`
- `Lifecycle Pattern`

Zusaetzlich ist er jetzt ein konkretes Beispiel fuer ein
`Decision System Pattern`.

## Enthaltene Dateien

### Rollen-Agenten

- `examples/CEO_ns/CEO_Core.ns`
- `examples/CEO_ns/StrategyAgent.ns`
- `examples/CEO_ns/RiskAgent.ns`
- `examples/CEO_ns/CapitalAgent.ns`
- `examples/CEO_ns/OperationsAgent.ns`
- `examples/CEO_ns/ConsensusLayer.ns`
- `examples/CEO_ns/NarrativeAgent.ns`
- `examples/CEO_ns/ExecutionDispatcher.ns`

### Operativer Lifecycle

- `examples/CEO_ns/CEO_Lifecycle.ns`
- `examples/CEO_ns/ceo_runtime_helper.py`
- `examples/CEO_ns/ceo_continuous_runtime.py`

### Beispieldaten

- `examples/CEO_ns/internal_telemetry.json`
- `examples/CEO_ns/external_market_signals.json`
- `examples/CEO_ns/event_signals.json`
- `examples/CEO_ns/policy_overrides.json`

## Domain Model

Der CEO-Lifecycle arbeitet mit einem strukturierten Zustandsmodell.
Die Runtime fuehrt unter anderem diese Bereiche:

- `capital`
  - `liquidity`
  - `burn_rate`
  - `allocations`
- `operations`
  - `capacity`
  - `utilization`
  - `bottlenecks`
- `strategy`
  - `active_initiatives`
  - `priorities`
  - `horizon`
- `risk`
  - `exposure`
  - `volatility`
  - `critical_flags`
- `market`
  - `demand`
  - `signals`
  - `opportunities`
- `policy`
- `decisions_history`
- `execution_log`

Damit arbeitet der Lifecycle nicht nur mit Text, sondern mit einem expliziten
Realitaetsmodell.

## Signal-System

Das Input-System ist bewusst signalorientiert.
Aktuell kommen die Daten aus drei Quellen:

- interne Telemetrie
- externe Marktsignale
- Event-Signale

Alle Quellen werden in ein gemeinsames Signalformat normalisiert:

```text
signal:
  signal_id
  type
  severity
  domain
  source
  title
  summary
  metrics
  payload
  timestamp
```

Dadurch koennen spaeter weitere Quellen hinzukommen, ohne die
Entscheidungslogik neu schreiben zu muessen.

## Agent Bundle Pattern

Die Einzeldateien wie `StrategyAgent.ns` oder `OperationsAgent.ns` sind
interaktive Agent-Bundles:

- eine Datei
- eine Rolle
- nach `ns.run` direkt per `agent run` nutzbar

Das ist sinnvoll fuer:

- Exploration
- manuelle Gegenpruefung
- prototypische Diskussionen
- isolierte Rollen-Reviews

Beispiel:

```powershell
ai use lmstudio <modellname>
ns.run .\examples\CEO_ns\OperationsAgent.ns
agent run OperationsAgent "GPU-Auslastung steigt ueber 87 Prozent, Partnerdruck nimmt zu."
```

## Flow Pattern

`CEO_Lifecycle.ns` ist der operative Flow.

Er bildet die Kette

```text
input -> transform -> merge -> decide -> act -> feedback
```

mit echten Zwischenartefakten ab:

- `domain_state`
- `governed_state`
- `unified_signals`
- `strategy_packet`
- `risk_packet`
- `capital_packet`
- `operations_packet`
- `decision_packet`
- `execution_plan`
- `outcome_packet`
- `final_state`
- `ceo_report`
- `artifact_paths`

Damit ist die Kette nicht implizit, sondern im Runtime-Output und Graph
nachvollziehbar.

## Lifecycle Pattern

Der CEO-Flow endet nicht bei Analyse, sondern fuehrt eine komplette
Lifecycle-Schleife aus:

1. Signale laden und normalisieren
2. Domain State aktualisieren
3. Optionen generieren
4. Risiko, Kapital und Operations bewerten
5. Konsens und Entscheidung bilden
6. Execution-Plan erzeugen
7. State fortschreiben
8. Outcome bewerten
9. Feedback in den State zurueckschreiben
10. Events emittieren
11. Reports und Artefakte persistieren

Genau dadurch wird aus einem Beispiel ein operatives Decision System.

## Entscheidungslogik

Die Entscheidung wird nicht einem LLM ueberlassen.
Der CEO-Kern nutzt eine gewichtete Bewertungslogik.

Aktuell:

```text
score =
  (expected_gain * 0.4)
  + (capital_feasibility * 0.2)
  - (risk_score * 0.3)
  + (operational_fit * 0.1)
```

Governance blockiert Optionen zusaetzlich, wenn:

- die Aktion verboten ist
- die Risikoschwelle ueberschritten wird
- die Kapitalgrenze ueberschritten wird
- der Kapitalplan nicht tragfaehig ist

Damit bleibt die Struktur deterministisch, auch wenn Einzelagenten spaeter
generativ erweitert werden.

## Governance und Policies

Die Policy-Datei steuert die harten Grenzen:

- `max_risk`
- `capital_limit`
- `minimum_runway_months`
- `forbidden_actions`

Diese Werte werden vor dem eigentlichen Zyklus in den State gemischt und
anschliessend im `ConsensusLayer` erzwungen.

## Memory und Feedback

Nach jeder Entscheidung werden Laufzeitdaten fortgeschrieben:

- `decisions_history`
- `execution_log`
- `last_decision`
- `last_execution`
- `last_outcome`

Der Outcome-Pfad ist:

```text
execution -> outcome -> feedback_update -> final_state
```

Damit verbessert sich der Zustand des Systems ueber mehrere Zyklen hinweg,
statt bei jedem Lauf bei Null zu beginnen.

## Event-System

Der Lifecycle emittiert benannte Events:

- `event.market.change`
- `event.capacity.limit`
- `event.capital.alert`
- `event.decision.made`
- `event.execution.done`
- `ceo_cycle_ready`

Zusatzlich sind Trigger auf:

- `board.review`
- `ceo.tick`
- `event.market.change`

Damit kann das System sowohl manuell als auch eventgetrieben laufen.

## Continuous Operation

Die kontinuierliche Laufzeit liegt in:

- `examples/CEO_ns/ceo_continuous_runtime.py`

Der Runner laedt `CEO_Lifecycle.ns`, emittiert `ceo.tick` und schreibt einen
kompakten Laufzeitstatus nach:

- `examples/CEO_ns/.nova_ceo/continuous_status.json`

Relevante Umgebungsvariablen:

- `NOVA_CEO_ONESHOT`
- `NOVA_CEO_INTERVAL`

Beispiel:

```powershell
cd .\examples\CEO_ns
$env:NOVA_CEO_ONESHOT = "1"
python .\ceo_continuous_runtime.py
```

## Persistente Artefakte

Jeder CEO-Zyklus schreibt unter `examples/CEO_ns/.nova_ceo/`:

- `ceo_report.json`
- `ceo_report.html`
- `latest_execution.json`
- `ceo_state.json`
- `decision_history.jsonl`
- `continuous_status.json` bei Nutzung des Continuous-Runners

Das sind keine bloessen Debug-Ausgaben, sondern die nachvollziehbare
Ausfuehrungsspur des Systems.

## Schnellstart

### 1. Gesamten CEO-Zyklus ausfuehren

```powershell
ns.run .\examples\CEO_ns\CEO_Lifecycle.ns
```

Erwartung:

- `flow: ceo_lifecycle`
- `context.outputs.decision_packet`
- `context.outputs.execution_plan`
- `context.outputs.final_state`
- `context.outputs.artifact_paths`

### 2. HTML-Report ansehen

Nach dem Lauf liegt der Report hier:

```text
examples/CEO_ns/.nova_ceo/ceo_report.html
```

### 3. Graph rendern

```powershell
ns.graph .\examples\CEO_ns\CEO_Lifecycle.ns
```

Das ist der schnellste Weg, um die Struktur als gerichteten Ausfuehrungsgraphen
zu verstehen.

### 4. Einzelne Rolle interaktiv nutzen

```powershell
ai use lmstudio <modellname>
ns.run .\examples\CEO_ns\RiskAgent.ns
agent run RiskAgent "Ein Partner fordert Kapital, waehrend die Kapazitaet knapp wird."
```

## Wichtiger Laufzeitunterschied

Die Einzel-Agenten sind fuer interaktive Nutzung mit einem generativen Modell
gedacht, typischerweise `LM Studio`.

Der eigentliche CEO-Lifecycle arbeitet aktuell anders:

- die Rollenlogik fuer den Lifecycle ist in `ceo_runtime_helper.py` deterministisch modelliert
- dadurch bleibt der Flow testbar, reproduzierbar und governance-faehig
- generative Agenten koennen darum herum genutzt werden, sind aber nicht der
  harte Entscheidungskern

Das ist absichtlich so.
Die Entscheidung soll strukturell belastbar sein und nicht am freien Modelltext
haengen.

## Typische Kommandos

Lifecycle ausfuehren:

```powershell
ns.run .\examples\CEO_ns\CEO_Lifecycle.ns
```

Eventgetrieben erneut triggern:

```powershell
ns.run .\examples\CEO_ns\CEO_Lifecycle.ns
event emit board.review "quarterly-board-cycle"
```

Graph ansehen:

```powershell
ns.graph .\examples\CEO_ns\CEO_Lifecycle.ns
```

Agentenbundle laden:

```powershell
ns.run .\examples\CEO_ns\StrategyAgent.ns
agent list
```

## Troubleshooting

### `agent run` liefert keine brauchbare Antwort

Dann ist meistens kein generativer Provider aktiv.

Setze vorher:

```powershell
ai use lmstudio <modellname>
```

### `CEO_Lifecycle.ns` soll ohne externes Modell laufen

Das ist bereits der Standard.
Der Lifecycle verwendet fuer seinen harten Entscheidungspfad keine freien
Modellantworten.

### Ich will den kontinuierlichen Modus testen

Nutze:

```powershell
cd .\examples\CEO_ns
$env:NOVA_CEO_ONESHOT = "1"
python .\ceo_continuous_runtime.py
```

Danach pruefen:

```text
examples/CEO_ns/.nova_ceo/continuous_status.json
```

## Verwandte Seiten

- [NovaDecisionSystem](./NovaDecisionSystem.md)
- [DecisionPatterns](./DecisionPatterns.md)
- [NovaAgents](./NovaAgents.md)
- [ExamplesAndRecipes](./ExamplesAndRecipes.md)
- [NovaCLI](./NovaCLI.md)
- [nsReference](./nsReference.md)
- [nsPatterns](./nsPatterns.md)

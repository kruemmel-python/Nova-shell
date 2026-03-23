# Decision Patterns

## Zweck

Diese Seite macht ein implizites Nova-shell-Muster explizit:

- Eingaben aufnehmen
- Signale transformieren
- Perspektiven zusammenfuehren
- eine Entscheidung ableiten
- eine Aktion ausgeben

Das ist kein reines CEO-Muster.
Es ist ein allgemeines Architekturpattern fuer mehrere Systemtypen.

Wenn du statt Pattern-Sprache eine formale Architekturdefinition suchst, lies
auch [NovaDecisionSystem](./NovaDecisionSystem.md).
Wenn du die Parser-, Graph- und Laufzeitsemantik formal sehen willst, lies
auch [NovaSemantics](./NovaSemantics.md).

## Das Kernmuster

Das abstrahierte Entscheidungsmodell lautet:

```text
input -> transform -> merge -> decide -> act
```

In Nova-shell heisst das meist:

```text
dataset -> agent/tool -> agent/tool -> agent -> agent/tool
```

## Muster 1: Agent Bundle Pattern

Ein `Agent Bundle` ist eine `.ns`-Datei, die nur Zustand und ein oder mehrere
deklarative `agent { ... }`-Bloecke enthaelt.

Beispiel:

```ns
state review_memory {
  backend: atheria
  namespace: review
}

agent reviewer {
  provider: shell
  model: active
  memory: review_memory
  system_prompt: "Du bist ein Reviewer."
  prompts: {v1: "Bewerte {{input}}"}
  prompt_version: v1
}
```

Eigenschaften:

- keine ausfuehrende `flow`-Logik noetig
- `ns.run` liefert ein kompaktes `agent_bundle`
- danach direkt ueber `agent run` nutzbar

Geeignet fuer:

- Rollenmodelle
- Einzelfunktionen
- Router
- Fachagenten

## Muster 2: Flow Pattern

Ein `Flow Pattern` ist ein expliziter Ablauf mit benannten Zwischenstufen.

Beispiel:

```ns
flow review {
  rss.fetch incident_feed -> snapshot
  analyst summarize incident_feed -> briefing
  system.log briefing
}
```

Eigenschaften:

- der Ablauf ist linear und nachvollziehbar
- Zwischenresultate sind benannt
- eignet sich fuer `ns.graph` und Debugging

Geeignet fuer:

- ETL-artige Prozesse
- Review-Pipelines
- Signalverarbeitung
- Automation Chains

## Muster 3: Lifecycle Pattern

Ein `Lifecycle Pattern` erweitert einen Flow zu einem wiederholbaren, reaktiven
oder statusbehafteten Betriebszyklus.

Typische Bausteine:

- `dataset`
- mehrere Agenten
- `state.set`
- `event.emit`
- optional `event { on: ... }`

Beispiel:

```ns
flow lifecycle {
  rss.fetch signals -> snapshot
  strategist assess signals -> proposal
  decision decide proposal -> verdict
  state.set latest_verdict verdict
  event.emit verdict_ready verdict
}
```

Eigenschaften:

- endet nicht nur in Text, sondern in Zustand und Event
- ist als Betriebszyklus lesbar
- laesst sich als Grundmuster fuer echte Runtime-Systeme verwenden

Geeignet fuer:

- Management-Zyklen
- Monitoring
- Security-Reaktionen
- Trading-Schritte
- Orchestrierung

## Muster 4: Decision Pattern

Das `Decision Pattern` ist die fachliche Abstraktion ueber den Lifecycle.

Es zerlegt Entscheidungslogik in fuenf Rollen:

1. `input`
2. `transform`
3. `merge`
4. `decide`
5. `act`

### Nova-shell-Abbildung

Ein typischer Zuschnitt ist:

- `dataset`: Eingangssignale
- `TransformAgent`: strukturierte Perspektive aus Rohdaten
- `ConstraintAgent` oder zweiter Transform-Schritt: Gegenperspektive
- `MergerAgent`: Verdichtung
- `DecisionAgent`: Urteil
- `ActionAgent`: operative Uebersetzung

## CEO-Beispiel

Im CEO-Beispiel liegt das Muster hier:

- `input`: `executive_signals`
- `transform`: `StrategyAgent`, `RiskAgent`, `CapitalAgent`
- `merge`: `ConsensusLayer`
- `decide`: `ConsensusLayer` plus `final_decision`
- `act`: `ExecutionDispatcher`

Siehe:

- [CEOAgentExamples](./CEOAgentExamples.md)
- `examples/CEO_ns/CEO_Lifecycle.ns`

## Generalisierung auf andere Domaenen

### Security Systems

```text
alerts -> normalize -> correlate -> classify -> respond
```

Moegliche Rollen:

- `AlertNormalizer`
- `ThreatScorer`
- `CorrelationLayer`
- `DecisionAgent`
- `ResponseDispatcher`

### Trading Systems

```text
market_data -> enrich -> combine -> decide -> execute
```

Moegliche Rollen:

- `SignalTransformer`
- `RiskEnvelope`
- `PortfolioMerger`
- `TradeDecision`
- `OrderDispatcher`

### AI Orchestrators

```text
requests -> analyze -> route_context -> decide_plan -> dispatch
```

Moegliche Rollen:

- `RequestAnalyzer`
- `CapabilityMatcher`
- `PlanMerger`
- `PlanDecision`
- `ExecutionRouter`

## Visualisierung mit `ns.graph`

Dieses Pattern wird besonders klar, wenn man den Graph rendert.

Beispiel:

```powershell
ns.graph .\examples\CEO_ns\CEO_Lifecycle.ns
ns.graph .\examples\decision_lifecycle_template.ns
```

Dann werden sichtbar:

- Knoten: Agenten, Dataset, Event, Tool-Schritte, Flow-Wurzel
- Kanten: Datenfluss, Alias-Uebergaenge, Ausfuehrungsreihenfolge

Das ist die schnellste Moeglichkeit, das System fuer Entwickler, Reviewer und
Architekturgespraeche verstaendlich zu machen.

## Referenz-Template

Ein generisches, sofort lauffaehiges Beispiel liegt hier:

- `examples/decision_lifecycle_template.ns`

Dieses Template zeigt dieselbe Struktur ohne CEO-spezifische Sprache.

## Verwandte Seiten

- [CEOAgentExamples](./CEOAgentExamples.md)
- [ExamplesAndRecipes](./ExamplesAndRecipes.md)
- [nsPatterns](./nsPatterns.md)
- [NovaAgents](./NovaAgents.md)
- [NovaRuntime](./NovaRuntime.md)

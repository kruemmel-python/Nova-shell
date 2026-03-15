# Component Model

## Zweck

Die Nova Language beschreibt Ressourcen als benannte Deklarationen.
Diese werden spaeter in AST-Knoten, Graph-Knoten und Runtime-Objekte ueberfuehrt.
Diese Seite erklaert die semantischen Bausteine des Systems.

## Kernobjekte

### `agent`

Rolle:
modellgestuetzte Ausfuehrungseinheit fuer Aufgaben in einem Flow.

Typische Eigenschaften:

- `model`
- `provider`
- `providers`
- `tools`
- `memory`
- `embeddings`
- `system_prompt`
- `prompt_version`
- `governance`

### `dataset`

Rolle:
strukturierte Quelle oder Zwischenspeicher fuer Datensaetze in Flows.

Typische Eigenschaften:

- `source`
- `items`
- `path`
- `format`

### `tool`

Rolle:
explizit benannte Operation mit Runtime-Bedeutung oder deklarierter Kommandoausfuehrung.

### `flow`

Rolle:
orchestrierter Ablauf aus Schritten, der spaeter zu Kanten und Knoten im Graphen wird.

### `event`

Rolle:
benannter Trigger fuer reaktive Workflows.

### `state`

Rolle:
deklarierter Zustandsschluessel oder Zustandsraum fuer Flows und Runtime.

### `service`

Rolle:
laufender Dienst mit Revisions-, Replica- und Routingdaten.

### `package`

Rolle:
installierbares Artefakt fuer Services oder Plattformteile.

### `system`

Rolle:
uebergeordnete Runtime-, Security- oder Placement-Konfiguration.

## Zuordnung zu AST und Graph

| Sprachbaustein | AST-Klasse | Graph-Klasse oder Laufzeitrolle |
| --- | --- | --- |
| `agent` | `AgentDeclaration` | `AgentNode` |
| `dataset` | `DatasetDeclaration` | `DatasetNode` |
| `tool` | `ToolDeclaration` | `ToolNode` |
| `service` | `ServiceDeclaration` | `ServiceNode` |
| `package` | `PackageDeclaration` | `PackageNode` |
| `flow` | `FlowDeclaration` | `FlowNode` |
| `event` | `EventDeclaration` | `EventNode` |
| `state` | `StateDeclaration` | Zustand in `RuntimeContext` |
| `system` | `SystemDeclaration` | Metadaten fuer Placement, Policy und Runtime |

## Modell vom Quelltext bis zur Laufzeit

```text
Declaration
  ->
AST Node
  ->
Graph Node oder Runtime Metadata
  ->
Execution / State / Service / Event
```

## CLI

Typische Kommandos, die direkt auf diesen Bausteinen aufsetzen:

- `ns.exec`
- `ns.run`
- `ns.graph`
- `ns.format`
- `ns.lint`

## API

Die Bausteine wirken indirekt auf die API, weil sie spaeter als Runtime-, Queue-, Service- und Agentenobjekte sichtbar werden.

## Testbare Beispiele

### Minimales Modell

```ns
agent reviewer {
  model: gpt-4o-mini
}

dataset reports {
  source: memory
}

flow review {
  reviewer summarize reports
}
```

### Erweiterte Komponenten

```ns
state mission {
  namespace: ops
}

event scheduler {
  on: schedule.tick
  flow: daily_ops
}
```

## Typische Fragen

### Ist `flow` nur eine Liste von Befehlen?

Nein. Ein `flow` ist die deklarative Quelle fuer einen Graph mit Knoten, Kanten und Laufzeitbedeutung.

### Ist `system` nur Konfiguration?

Nicht nur. `system` beeinflusst oft Placement, Policy, Tenant- oder Runtime-Verhalten.

### Wo sieht man die technische Umsetzung?

In [ParserAndASTReference](./ParserAndASTReference.md), [NovaGraphEngine](./NovaGraphEngine.md) und [NovaRuntime](./NovaRuntime.md).

## Verwandte Seiten

- [NovaLanguage](./NovaLanguage.md)
- [ParserAndASTReference](./ParserAndASTReference.md)
- [NovaGraphEngine](./NovaGraphEngine.md)
- [NovaRuntime](./NovaRuntime.md)

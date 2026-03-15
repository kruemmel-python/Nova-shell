# Component Model

## Zweck

Die Nova Language beschreibt Ressourcen als benannte Deklarationen.
Diese werden spaeter in AST-Knoten und Graph-Knoten ueberfuehrt.

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

## Methoden und Schnittstellen

### Zuordnung zu AST und Graph

| Sprachbaustein | AST-Klasse | Graph-Klasse |
| --- | --- | --- |
| `agent` | `AgentDeclaration` | `AgentNode` |
| `dataset` | `DatasetDeclaration` | `DatasetNode` |
| `tool` | `ToolDeclaration` | `ToolNode` |
| `service` | `ServiceDeclaration` | `ServiceNode` |
| `package` | `PackageDeclaration` | `PackageNode` |
| `flow` | `FlowDeclaration` | `FlowNode` |
| `event` | `EventDeclaration` | `EventNode` |
| `state` | `StateDeclaration` | Zustand in `RuntimeContext` |
| `system` | `SystemDeclaration` | Metadaten fuer Placement und Policy |

## CLI

Typische Kommandos, die auf diesen Bausteinen aufsetzen:

- `ns.exec`
- `ns.run`
- `ns.graph`
- `ns.format`

## API

Die Bausteine wirken indirekt auf die API, weil sie spaeter als Runtime-, Queue-, Service- und Agentenobjekte sichtbar werden.

## Beispiele

```nova
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

## Verwandte Seiten

- [NovaLanguage](./NovaLanguage.md)
- [ParserAndASTReference](./ParserAndASTReference.md)
- [NovaRuntime](./NovaRuntime.md)
- [PageTemplate](./PageTemplate.md)

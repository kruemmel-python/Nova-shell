# Nova Language

## Zweck

Nova Language ist die deklarative Sprache fuer Ressourcen, Flows und Plattformsteuerung.

## Sprachbausteine

- `agent`
- `dataset`
- `flow`
- `state`
- `event`
- `tool`
- `service`
- `package`
- `system`
- `import`

## Beispiel

```text
agent researcher {
  model: llama3
}

dataset tech_rss {
  source: rss
}

flow radar {
  rss.fetch tech_rss -> fetched
  researcher summarize tech_rss -> summary
}
```

## Ziele

- deklarative Systembeschreibung
- graphbasierte Ausfuehrung
- Agenten- und Tool-Orchestrierung
- Events und Trigger
- Toolchain-faehige Module

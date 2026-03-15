# Nova Language

## Zweck

Nova Language ist die deklarative Sprache von Nova-shell.
Sie beschreibt Ressourcen, Flows, Events, Services und Packages in `.ns`-Dateien.

Die Sprache dient als Eingang fuer:

- Parser
- AST
- Modul-Loader
- Lockfiles
- Graph-Compiler
- Runtime
- Test-Runner

## Kernobjekte

- `import`
- `agent`
- `dataset`
- `tool`
- `flow`
- `event`
- `state`
- `service`
- `package`
- `system`

Zentrale Klassen:

- `NovaParser`
- `NovaAST`
- `ImportDeclaration`
- `AgentDeclaration`
- `DatasetDeclaration`
- `ToolDeclaration`
- `FlowDeclaration`
- `EventDeclaration`

## Methoden und Schnittstellen

Wichtige Parser-Methoden:

- `parse`
- `parse_file`
- `register_extension`

Wichtige Sprachschnittstellen:

- Dateiimporte
- Registry-Importe
- Flow-Schritte mit optionalem Alias `->`

## CLI

Typische Sprachpfade in der CLI:

- `ns.exec`
- `ns.run`
- `ns.graph`
- `ns.format`
- `ns.lint`
- `ns.test`

## API

Direkte HTTP-Endpunkte fuer den Parser gibt es nicht.
Die Sprache wirkt ueber Runtime, Toolchain und Control-Plane indirekt in die API hinein.

## Beispiele

### Grundsyntax

```ns
agent helper {
  model: local
}

dataset notes {
  items: [{text: "hello nova"}]
}

flow boot {
  helper summarize notes -> summary
}
```

### Flows

`flow` ist der wichtigste aktive Baustein.
Ein Flow besteht aus Properties und Schritten.

```ns
flow radar {
  entry: true
  rss.fetch tech_rss -> fetched
  researcher summarize tech_rss -> summary
  event.emit dataset.updated
}
```

Ein Flow-Schritt besteht aus:

- Operation
- Argumenten
- optionalem Alias mit `->`

### Imports und Module

Nova Language unterstuetzt:

- Dateiimporte
- Registry-Importe

Diese werden ueber `NovaModuleLoader` aufgeloest.

### Agent plus Flow

```ns
agent reviewer {
  provider: openai
  model: gpt-4o-mini
}

flow review {
  reviewer summarize report -> result
}
```

### Eventgetriebene Automation

```ns
event refresh_on_update {
  on: dataset.updated
  flow: radar
}
```

### Service und Package

```ns
package analytics_pkg {
  version: 1.0.0
  entrypoint: examples/service_package_platform.ns
}

service analytics_api {
  replicas: 2
  package: analytics_pkg
}
```

## Verwandte Seiten

- [ParserAndASTReference](./ParserAndASTReference.md)
- [ComponentModel](./ComponentModel.md)
- [RuntimeMethodReference](./RuntimeMethodReference.md)
- [ExamplesAndRecipes](./ExamplesAndRecipes.md)
- [PageTemplate](./PageTemplate.md)

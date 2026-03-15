# Nova Language

## Zweck

Nova Language ist die deklarative Sprache von Nova-shell.
Sie beschreibt Ressourcen, Flows, Events, Services und Packages in `.ns`-Dateien und bildet damit den sprachlichen Eingang in Parser, Graph-Compiler, Runtime und Toolchain.

## Sprachbausteine

| Baustein | Rolle |
| --- | --- |
| `import` | bindet weitere Dateien oder Registry-Module ein |
| `agent` | beschreibt Agentenrollen, Modelle, Tools und Memory |
| `dataset` | beschreibt Datenquellen oder Datenobjekte |
| `tool` | beschreibt aufrufbare Werkzeuge |
| `flow` | beschreibt ausfuehrbare Graphen |
| `event` | beschreibt Trigger und ihre Ziel-Flows |
| `state` | beschreibt Laufzeitzustand oder Namespaces |
| `service` | beschreibt laufende Dienste |
| `package` | beschreibt installierbare Artefakte |
| `system` | beschreibt Runtime-, Policy- oder Placement-Kontext |

## Zentrale Klassen

- `NovaParser`
- `NovaAST`
- `ImportDeclaration`
- `AgentDeclaration`
- `DatasetDeclaration`
- `ToolDeclaration`
- `FlowDeclaration`
- `EventDeclaration`
- `ServiceDeclaration`
- `PackageDeclaration`

## Sprachmodell

Nova Language ist keine lose Sammlung von Textbloecken, sondern wird schrittweise verarbeitet:

```text
.ns Source
  ->
Parser
  ->
AST
  ->
Graph Compiler
  ->
Runtime
```

## Methoden und Schnittstellen

Wichtige Parser-Methoden:

- `parse`
- `parse_file`
- `register_extension`

Wichtige Toolchain-Schnittstellen:

- Dateiimporte
- Registry-Importe
- Lockfiles
- Formatierung
- Linting
- `.ns`-Tests

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
Die Sprache wirkt ueber Runtime, Toolchain und Control Plane indirekt in die API hinein.

## Testbare Beispiele

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

### Flow mit Aliasen

```ns
flow radar {
  rss.fetch tech_rss -> fetched
  researcher summarize tech_rss -> summary
  event.emit dataset.updated
}
```

Ein Flow-Schritt besteht typischerweise aus:

- Operation
- Argumenten
- optionalem Alias mit `->`

### Imports und Module

```ns
import "agents/research.ns"
import "flows/radar.ns"
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
  source: "./dist/analytics.tar"
}

service analytics_api {
  replicas: 2
  package: analytics_pkg
}
```

## Typische Fehler und Fragen

### Wann benutze ich `.ns` statt direkter CLI-Befehle?

Wenn der Ablauf reproduzierbar, versionierbar oder graphbasiert sein soll.

### Wo sehe ich, ob mein Programm syntaktisch korrekt ist?

Am schnellsten mit:

```powershell
ns.graph datei.ns
```

### Wo beginnt die Fehlersuche bei Imports?

Bei Modulpfad, Lockfile, Loader-Kontext und Toolchain.

## Verwandte Seiten

- [nsCreate](./nsCreate.md)
- [nsReference](./nsReference.md)
- [nsPatterns](./nsPatterns.md)
- [ParserAndASTReference](./ParserAndASTReference.md)
- [ComponentModel](./ComponentModel.md)
- [NovaGraphEngine](./NovaGraphEngine.md)
- [ToolchainAndTesting](./ToolchainAndTesting.md)
- [ExamplesAndRecipes](./ExamplesAndRecipes.md)

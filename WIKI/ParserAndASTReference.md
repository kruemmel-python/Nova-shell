# Parser and AST Reference

## Zweck

Diese Seite dokumentiert die Sprachvorderseite von Nova-shell:
Parsing, Modulaufloesung, AST-Struktur und den Uebergang in den Graph-Compiler.

## Kernobjekte

### Uebersicht

Der typische Pfad sieht so aus:

```text
.ns source
  -> NovaParser
  -> NovaAST
  -> NovaGraphCompiler
  -> ExecutionGraph
  -> NovaRuntime
```

### `NovaParser`

Modul: `nova.parser.parser`

`NovaParser` ist der Einstiegspunkt fuer das Einlesen von `.ns`-Programmen.
Die Klasse unterstuetzt sowohl Dateien als auch In-Memory-Strings und kann Syntax-Erweiterungen registrieren.

### Wichtige Methoden

| Methode | Zweck |
| --- | --- |
| `parse(source, source_name="...")` | Parst einen Text und liefert `NovaAST`. |
| `parse_file(path)` | Liest eine Datei und liefert `NovaAST`. |
| `register_extension(name, handler)` | Registriert parserseitige Erweiterungen. |

### Beispiel

```python
from nova.parser.parser import NovaParser

parser = NovaParser()
ast = parser.parse(
    """
    dataset tech_rss {
      source: rss
    }
    """,
    source_name="inline.ns",
)
print(ast.datasets[0].name)
```

### AST-Root: `NovaAST`

Modul: `nova.parser.ast`

`NovaAST` sammelt alle Deklarationen eines Programms.
Wichtige Sammlungen sind:

- `imports`
- `agents`
- `datasets`
- `tools`
- `services`
- `packages`
- `states`
- `systems`
- `events`
- `flows`

### Deklarationsknoten

### `ImportDeclaration`

Repraesentiert `import`-Anweisungen fuer modulare Programme.

Beispiel:

```nova
import "platform/base.ns"
import "agents/research.ns"
```

### `AgentDeclaration`

Beschreibt einen Agenten und seine Eigenschaften.

Typische Felder:

- `name`
- `attributes`
- `span`

Beispiel:

```nova
agent researcher {
  model: gpt-4o-mini
  memory: shared
}
```

### `DatasetDeclaration`

Beschreibt eine Datenquelle oder ein persistentes Dataset.

Beispiel:

```nova
dataset tech_rss {
  source: rss
  url: https://example.com/feed.xml
}
```

### `ToolDeclaration`

Deklariert Tools, die in Flows oder Agenten genutzt werden koennen.

Beispiel:

```nova
tool embedder {
  backend: ai.embed
}
```

### `ServiceDeclaration`

Beschreibt deploybare Services in der Service Fabric.

Beispiel:

```nova
service api {
  image: nova-api:latest
  port: 8080
}
```

### `PackageDeclaration`

Beschreibt paketierbare oder wiederverwendbare Komponenten.

Beispiel:

```nova
package analytics {
  version: 1.0.0
  source: ./analytics
}
```

### `StateDeclaration`

Definiert persistente oder flussbezogene Zustandsbereiche.

### `SystemDeclaration`

Beschreibt Systemkonfigurationen, Policies oder Infrastrukturbloecke.

### `EventDeclaration`

Definiert benannte Events oder Trigger.

### `FlowDeclaration`

Enthaelt einen ausfuehrbaren Flow mit `FlowStep`-Eintraegen.

Beispiel:

```nova
flow radar {
  rss.fetch tech_rss
  atheria.embed tech_rss
  researcher summarize tech_rss
}
```

### `FlowStep`

Ein `FlowStep` repraesentiert genau eine deklarative Aktion im Flow.
Im Compiler wird daraus je nach Inhalt ein Tool-, Agenten- oder Systemschritt.

Typische Informationen:

- Verb oder Aktion
- Zielobjekt
- Argumente
- Quellposition

### `SourceSpan`

Jeder AST-Knoten kann eine `SourceSpan` tragen.
Sie dient fuer:

- klare Fehlermeldungen
- LSP-Hover und Positionsmapping
- Linter-Diagnosen

## Methoden und Schnittstellen

### Fehlermodell

Parserfehler werden ueber die Fehlerklassen in `nova.parser.errors` gemeldet.
Die Fehlermeldungen sollen immer mindestens enthalten:

- Quelldatei
- Zeile
- Spalte
- kurze strukturelle Ursache

### Von AST zu Graph

Nach dem Parsing uebersetzt `NovaGraphCompiler` die Deklarationen in Laufzeitknoten.

| AST-Knoten | Graph-Knoten |
| --- | --- |
| `AgentDeclaration` | `AgentNode` |
| `DatasetDeclaration` | `DatasetNode` |
| `ToolDeclaration` | `ToolNode` |
| `ServiceDeclaration` | `ServiceNode` |
| `PackageDeclaration` | `PackageNode` |
| `EventDeclaration` | `EventNode` |
| `FlowDeclaration` | `FlowNode` plus `ExecutionEdge` |

## CLI

Parser und AST werden indirekt ueber diese Kommandos genutzt:

- `ns.exec`
- `ns.run`
- `ns.graph`
- `ns.format`
- `ns.lint`
- `ns.test`

## API

Es gibt keine direkte Parser-HTTP-API.
Der Parser wirkt ueber Runtime und Toolchain in die Plattform hinein.

## Beispiele

### Praktisches Parsing-Beispiel

```python
from nova.parser.parser import NovaParser
from nova.graph.compiler import NovaGraphCompiler

parser = NovaParser()
ast = parser.parse_file("examples/market_radar.ns")

print("Agents:", [agent.name for agent in ast.agents])
print("Flows:", [flow.name for flow in ast.flows])

graph = NovaGraphCompiler().compile(ast)
print("Node count:", len(graph.nodes))
print("Edge count:", len(graph.edges))
```

## Toolchain-Bezug

Die Toolchain nutzt Parser und AST an mehreren Stellen:

- `NovaModuleLoader` fuer Imports und Modulgraphen
- `NovaFormatter` fuer strukturbasiertes Formatieren
- `NovaLinter` fuer Diagnosen
- `NovaLanguageServerFacade` fuer Editorfunktionen
- `NovaTestRunner` fuer deklarative Programmtests

## Verwandte Seiten

- [ClassReference](./ClassReference.md)
- [CodeReferenceIndex](./CodeReferenceIndex.md)
- [RuntimeMethodReference](./RuntimeMethodReference.md)
- [NovaLanguage](./NovaLanguage.md)
- [PageTemplate](./PageTemplate.md)

# nsReference

## Zweck

Diese Seite ist die kompakte Sprachreferenz fuer Nova Language.
Sie ist nicht als Lernpfad gedacht, sondern als Nachschlagewerk fuer Syntax, Bausteine, typische Felder und den praktischen Einsatz einzelner Konstrukte.

Wenn du `.ns` erst lernen willst, beginne mit [nsCreate](./nsCreate.md).

## Grundform einer Deklaration

Nova Language besteht aus benannten Bloecken:

```ns
agent researcher {
  model: llama3
}
```

Allgemeines Muster:

```text
keyword name {
  property: value
}
```

## Sprachbausteine im Ueberblick

| Baustein | Zweck | Typische Felder |
| --- | --- | --- |
| `import` | bindet andere Dateien oder Module ein | Pfad oder Registryziel |
| `system` | legt Runtime- oder Plattformkontext fest | `mode`, `tenant`, `cluster`, `observability` |
| `state` | beschreibt Zustand oder Namespaces | `namespace`, `backend` |
| `agent` | beschreibt modellgestuetzte Akteure | `provider`, `model`, `tools`, `memory` |
| `dataset` | beschreibt Datenquellen oder Datenobjekte | `source`, `path`, `format`, `items` |
| `tool` | beschreibt benannte Aktionen | `command`, `capability`, `system` |
| `flow` | beschreibt die eigentliche Ausfuehrungslogik | Schritte und optionale Eigenschaften |
| `event` | verbindet Signale mit Flows | `on`, `flow` |
| `package` | beschreibt installierbare Artefakte | `version`, `source`, `entrypoint` |
| `service` | beschreibt laufende Dienste | `package`, `replicas`, `ingress` |

## Werte und Literale

Nova Language verwendet typischerweise:

- Strings
- Zahlen
- Booleans
- Listen
- Maps

### String

```ns
model: "gpt-4o-mini"
```

oder kuerzer:

```ns
model: llama3
```

### Zahl

```ns
replicas: 2
```

### Boolean

```ns
leader: true
```

### Liste

```ns
tools: [atheria.embed, system.log]
```

### Map

```ns
configs: {backend_cfg: {mode: "prod", cache: "enabled"}}
```

## `import`

Bindet weitere `.ns`-Dateien ein.

```ns
import "agents/research.ns"
import "flows/radar.ns"
```

Typischer Einsatz:

- grosse Programme aufteilen
- Agenten, Datasets und Flows getrennt organisieren

## `system`

Legt System- oder Plattformkontext fest.

```ns
system control_plane {
  mode: mesh
  tenant: ops
  cluster: nova-edge
  observability: enabled
}
```

Typische Felder:

- `mode`
- `tenant`
- `namespace`
- `cluster`
- `node_id`
- `leader`
- `capability`
- `observability`

## `state`

Beschreibt Laufzeitzustand oder einen Namensraum.

```ns
state mission {
  namespace: ai_os_cluster
}
```

oder:

```ns
state research_memory {
  backend: atheria
  namespace: market_radar
}
```

## `agent`

Beschreibt einen Agenten.

```ns
agent strategist {
  provider: atheria
  model: atheria-core
  tools: [publish_signal, atheria.embed]
  memory: mission
}
```

Typische Felder:

- `provider`
- `providers`
- `model`
- `tools`
- `memory`
- `embeddings`
- `system_prompt`
- `prompts`
- `prompt_version`
- `governance`

## `dataset`

Beschreibt Daten.

```ns
dataset signals {
  source: rss
  path: sample_news.json
  knowledge: atheria
}
```

oder direkt eingebettet:

```ns
dataset incidents {
  items: [{title: "GPU cluster drift"}, {title: "Worker restart storm"}]
}
```

Typische Felder:

- `source`
- `path`
- `format`
- `items`
- `knowledge`

## `tool`

Beschreibt eine benannte Aktion.

```ns
tool publish_signal {
  command: system.log {{value0}}
  capability: cpu
  system: control_plane
}
```

Typische Felder:

- `command`
- `capability`
- `system`
- `selector`

## `flow`

Der wichtigste aktive Baustein.

```ns
flow daily_ops {
  rss.fetch signals -> fresh_signals
  strategist prioritize signals -> action_plan
  publish_signal action_plan
}
```

### Schrittform

Grundmuster:

```text
operation argument1 argument2 -> alias
```

Beispiele:

```ns
rss.fetch tech_rss -> fresh_news
atheria.embed tech_rss -> embedded_news
researcher summarize tech_rss -> briefing
```

### Typische Flow-Eigenschaften

Je nach Beispiel oder Runtimepfad koennen zusaetzliche Properties existieren, etwa:

- `entry`
- `system`
- `tenant`
- `required_roles`
- `selector`

## `event`

Verbindet Signale mit Flows.

```ns
event scheduler {
  on: schedule.tick
  flow: daily_ops
}
```

Typische Felder:

- `on`
- `flow`

## `package`

Beschreibt installierbare Artefakte.

```ns
package base_sdk {
  version: 1.0.0
  source: "./dist/base-sdk.tar"
}
```

## `service`

Beschreibt laufende Dienste.

```ns
service backend {
  package: base_sdk
  replicas: 2
  ingress: [{host: "backend.local", path: "/api", target_port: 8080}]
}
```

Typische Felder:

- `package`
- `replicas`
- `configs`
- `volumes`
- `ingress`
- `autoscale`

## Testbare Arbeitsfolge

```powershell
ns.graph datei.ns
ns.format datei.ns
ns.lint datei.ns
ns.run datei.ns
ns.test datei.ns
```

## Typische Referenzfragen

### Wie sieht ein gueltiger Flow-Schritt aus?

Als Operation mit Argumenten und optionalem Alias.

### Wann brauche ich `system`?

Wenn Runtime-, Tenant-, Placement- oder Plattformverhalten explizit im Programm beschrieben werden soll.

### Wann teile ich Dateien mit `import`?

Sobald Agenten, Datasets, Flows und Services nicht mehr uebersichtlich in einer einzigen Datei bleiben.

## Verwandte Seiten

- [nsCreate](./nsCreate.md)
- [nsPatterns](./nsPatterns.md)
- [NovaLanguage](./NovaLanguage.md)
- [ComponentModel](./ComponentModel.md)
- [ParserAndASTReference](./ParserAndASTReference.md)

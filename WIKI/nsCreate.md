# nsCreate

## Zweck

Diese Seite ist der eigentliche Schreibleitfaden fuer Nova Language.
Sie soll jemandem, der Nova-shell noch nicht kennt, beibringen, wie man echte `.ns`-Programme von Grund auf schreibt, prueft und erweitert.

## Fuer wen diese Seite gedacht ist

- Nutzer, die ihre ersten `.ns`-Dateien schreiben wollen
- Entwickler, die von Shell-Befehlen auf deklarative Programme wechseln
- Maintainer, die neue Sprachbausteine oder Beispielprogramme dokumentieren muessen

## Das mentale Modell von `.ns`

Ein `.ns`-Programm ist keine lose Liste von Befehlen.
Es ist eine deklarative Beschreibung von:

- Ressourcen
- Datenquellen
- Agenten
- Tools
- Flows
- Events
- System- und Zustandskontext

Die Datei wird spaeter so verarbeitet:

```text
.ns
  ->
Parser
  ->
AST
  ->
Graph
  ->
Runtime
```

## Die Bausteine, die du lernen musst

| Baustein | Wofuer er da ist |
| --- | --- |
| `import` | weitere `.ns`-Dateien oder Module einbinden |
| `system` | Runtime-, Placement-, Policy- oder Plattformkontext festlegen |
| `state` | Namespaces oder Laufzeitzustand definieren |
| `agent` | modellgestuetzte Akteure definieren |
| `dataset` | Datenquellen oder Datensaetze definieren |
| `tool` | benannte Aktionen definieren |
| `flow` | eigentliche Ausfuehrungslogik beschreiben |
| `event` | Flow-Ausloeser und Trigger definieren |
| `service` | laufende Dienste definieren |
| `package` | installierbare Artefakte definieren |

## So schreibst du dein erstes `.ns`-Programm

### Schritt 1: klein anfangen

Datei `hello.ns`:

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

### Schritt 2: Graph ansehen

```powershell
ns.graph hello.ns
```

Wenn dieser Schritt funktioniert, ist die Grundstruktur der Datei bereits plausibel.

### Schritt 3: Programm ausfuehren

```powershell
ns.run hello.ns
```

## Die Reihenfolge, in der du `.ns` lernen solltest

1. `agent`
2. `dataset`
3. `flow`
4. `event`
5. `state`
6. `tool`
7. `system`
8. `service` und `package`
9. `import`

Diese Reihenfolge ist sinnvoll, weil du damit zuerst das Kernmuster von Daten plus Aktion plus Ablauf beherrschst.

## Die wichtigsten Schreibregeln

### 1. Deklarationen sind benannte Bloecke

Jede wichtige Ressource bekommt einen Namen:

```ns
agent researcher {
  model: llama3
}
```

### 2. Eigenschaften stehen im Block

Eigenschaften sind `name: wert`:

```ns
dataset tech_rss {
  source: rss
  path: sample_news.json
  format: json
}
```

### 3. `flow` ist der aktive Teil

Hier definierst du, was ausgefuehrt wird:

```ns
flow radar {
  rss.fetch tech_rss -> fetched
  researcher summarize tech_rss -> summary
}
```

### 4. `->` gibt einem Schritt einen Alias

Das ist wichtig, wenn du Zwischenergebnisse benennen willst:

```ns
rss.fetch tech_rss -> fetched
```

### 5. `event` macht Programme reaktiv

```ns
event on_update {
  on: dataset.updated
  flow: radar
}
```

## Wie man jeden Baustein schreibt

### `agent`

Ein Agent beschreibt, wer eine modellgestuetzte Aufgabe ausfuehrt.

```ns
agent reviewer {
  provider: openai
  model: gpt-4o-mini
  tools: [system.log]
  memory: review_memory
}
```

Typische Felder:

- `provider`
- `providers`
- `model`
- `tools`
- `memory`
- `system_prompt`
- `prompts`
- `prompt_version`
- `governance`

### `dataset`

Ein Dataset beschreibt, welche Daten ein Flow sieht.

```ns
dataset incidents {
  items: [{title: "GPU cluster drift"}, {title: "Worker restart storm"}]
}
```

oder:

```ns
dataset tech_rss {
  source: rss
  path: sample_news.json
  format: json
}
```

### `tool`

Ein Tool ist eine benannte Aktion.

```ns
tool publish_signal {
  command: system.log {{value0}}
  capability: cpu
}
```

### `state`

State ist fuer Laufzeitzustand und Namespaces da.

```ns
state research_memory {
  backend: atheria
  namespace: market_radar
}
```

### `system`

`system` beschreibt Plattform- oder Laufzeitkontext.

```ns
system local_control {
  mode: local
  observability: structured
}
```

### `flow`

Ein Flow ist die wichtigste Schreibform in Nova Language.

```ns
flow radar {
  rss.fetch tech_rss -> fresh_news
  atheria.embed tech_rss -> embedded_news
  researcher summarize tech_rss -> briefing
}
```

Ein Flow-Schritt hat typischerweise:

- eine Operation
- Eingaben
- optional einen Alias

### `event`

Events verbinden Signale mit Flows:

```ns
event scheduler {
  on: schedule.tick
  flow: daily_ops
}
```

### `package` und `service`

Diese Bausteine brauchst du, wenn `.ns` ueber reine Flow-Ausfuehrung hinaus in die Plattform geht.

```ns
package base_sdk {
  version: 1.0.0
  source: "./dist/base-sdk.tar"
}

service backend {
  package: base_sdk
  replicas: 2
}
```

## Ein volleres Beispiel

```ns
system local_control {
  mode: local
  observability: structured
}

state research_memory {
  backend: atheria
  namespace: market_radar
}

agent researcher {
  model: llama3
  tools: [atheria.embed, system.log]
  memory: research_memory
  embeddings: atheria
}

dataset tech_rss {
  source: rss
  path: sample_news.json
  format: json
}

flow radar {
  rss.fetch tech_rss -> fresh_news
  atheria.embed tech_rss -> embedded_news
  researcher summarize tech_rss -> briefing
}

event new_information {
  on: new_information
  flow: radar
}
```

## Imports und groessere Programme

Wenn ein Programm groesser wird, trennst du es in mehrere Dateien:

```ns
import "agents/research.ns"
import "flows/radar.ns"
import "datasets/news.ns"
```

Empfehlung:

- Agenten in `agents/`
- Datasets in `datasets/`
- Flows in `flows/`
- Systemkontexte in `systems/`

## Wie du `.ns` sauber entwickelst

### 1. Erst schreiben

Erstelle die Datei und beginne klein.

### 2. Dann Graph pruefen

```powershell
ns.graph datei.ns
```

### 3. Dann formatieren und linten

```powershell
ns.format datei.ns
ns.lint datei.ns
```

### 4. Dann ausfuehren

```powershell
ns.run datei.ns
```

### 5. Dann testen

```powershell
ns.test datei.ns
```

## Typische Fehler beim Schreiben von `.ns`

### `ns.graph` scheitert sofort

Dann ist die Struktur oder Syntax der Datei kaputt.

### `ns.graph` geht, `ns.run` aber nicht

Dann ist der Text gueltig, aber ein Runtime-, Tool-, Provider- oder Datenproblem liegt vor.

### Imports funktionieren nicht

Dann sind meist Pfad, Loader-Kontext oder Modulaufbau falsch.

### Ein Flow ist zu gross und unklar

Dann teile ihn in mehrere Flows, Tools oder importierte Module.

## Ein sinnvoller Lernpfad fuer `.ns`

1. schreibe einen Agent plus Dataset plus Flow
2. fuege einen Alias `->` hinzu
3. ergaenze `state`
4. ergaenze `event`
5. trenne die Datei per `import`
6. baue `tool` ein
7. gehe erst danach an `service` und `package`

## Was du nach dieser Seite lesen solltest

Wenn du Syntax und Schreibweise vertiefen willst:

- [NovaLanguage](./NovaLanguage.md)
- [nsReference](./nsReference.md)
- [nsPatterns](./nsPatterns.md)
- [ComponentModel](./ComponentModel.md)
- [ParserAndASTReference](./ParserAndASTReference.md)

Wenn du Ausfuehrung verstehen willst:

- [NovaRuntime](./NovaRuntime.md)
- [NovaGraphEngine](./NovaGraphEngine.md)
- [DataFlow](./DataFlow.md)

Wenn du Beispiele willst:

- [ExamplesAndRecipes](./ExamplesAndRecipes.md)
- [TutorialTechnologyRadar](./TutorialTechnologyRadar.md)
- [ProgrammingWithNovaShell](./ProgrammingWithNovaShell.md)

## Verwandte Seiten

- [NovaLanguage](./NovaLanguage.md)
- [nsReference](./nsReference.md)
- [nsPatterns](./nsPatterns.md)
- [ProgrammingWithNovaShell](./ProgrammingWithNovaShell.md)
- [ExamplesAndRecipes](./ExamplesAndRecipes.md)
- [ParserAndASTReference](./ParserAndASTReference.md)
- [NovaRuntime](./NovaRuntime.md)

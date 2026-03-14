# Nova Lernhandbuch

> **Zielgruppe:** Entwickler:innen, Architekt:innen und AI-Engineers, die Nova als deklarative Sprache für AI-Systeme produktiv einsetzen wollen.

Dieses Handbuch ist als **Lehrdokumentation** aufgebaut: vom mentalen Modell über Syntax und Architektur bis zur täglichen Praxis in echten Projekten.

---

## Inhaltsverzeichnis

1. [Was ist Nova?](#was-ist-nova)
2. [Das mentale Modell: "Systeme deklarieren, nicht skripten"](#das-mentale-modell-systeme-deklarieren-nicht-skripten)
3. [Schnellstart in 10 Minuten](#schnellstart-in-10-minuten)
4. [Grundbausteine der Sprache](#grundbausteine-der-sprache)
5. [Flow-Design und Ausführungsgraph](#flow-design-und-ausführungsgraph)
6. [Events und reaktive Orchestrierung](#events-und-reaktive-orchestrierung)
7. [Memory, Sensoren und Mesh](#memory-sensoren-und-mesh)
8. [CLI-Toolchain (`nova`)](#cli-toolchain-nova)
9. [Debugging, Fehlerbilder und Validierung](#debugging-fehlerbilder-und-validierung)
10. [Projektstruktur und Best Practices](#projektstruktur-und-best-practices)
11. [Patterns für produktive AI-Systeme](#patterns-für-produktive-ai-systeme)
12. [FAQ](#faq)
13. [Von Nova-Shell zu Nova Language: Migrationshinweise](#von-nova-shell-zu-nova-language-migrationshinweise)

---

## Was ist Nova?

Nova ist eine **deklarative Programmiersprache für AI-Systeme**. Ein `.ns`-Programm beschreibt nicht Schritt-für-Schritt-Logik wie ein imperatives Skript, sondern eine **System-Topologie**:

- welche Agents existieren,
- welche Datenquellen verfügbar sind,
- welche Flows laufen,
- auf welche Events reagiert wird,
- welche Ressourcen (Memory, Mesh, Sensorik) bereitstehen.

Nova wird danach kompiliert zu:

```text
.ns Source
 -> Lexer
 -> Parser
 -> AST
 -> Graph Compiler
 -> Execution DAG
 -> Runtime Scheduler
```

Damit ist Nova gleichzeitig:

- **Sprache** (Modeling Layer),
- **Compiler-Toolchain** (`nova build|graph|plan|run`),
- **AI Runtime/OS-Layer** (Agent-, Event-, Memory- und Mesh-Orchestrierung).

---

## Das mentale Modell: "Systeme deklarieren, nicht skripten"

Wenn du aus Python/Bash kommst, denkst du oft in Reihenfolgen:

1. Lade Datei
2. Verarbeite Daten
3. Rufe Modell auf
4. Speichere Ergebnis

In Nova formulierst du stattdessen:

- _Welche Komponenten gibt es?_ (`agent`, `dataset`, `memory`, `tool`)
- _Wie hängen sie zusammen?_ (`flow`)
- _Wann startet was?_ (`event`)

### Entscheidender Unterschied

- **Imperativ:** "Mach zuerst A, dann B."
- **Nova deklarativ:** "Dieses System besteht aus A, B, C; bei Ereignis X soll Flow Y laufen."

Die Runtime übernimmt Planung, DAG-Ausführung und Event-Dispatch.

---

## Schnellstart in 10 Minuten

### 1) Beispielprogramm erstellen

`examples/hello_radar.ns`:

```ns
agent researcher {
model: llama3
}

dataset tech_rss {
source: rss
url: https://example.com/rss
}

flow radar {
rss.fetch tech_rss
researcher summarize tech_rss
emit dataset.updated tech_rss
}

event refresh_on_update {
on dataset.updated
do radar
}
```

### 2) Validieren + Build

```bash
nova build examples/hello_radar.ns
```

Du erhältst den kompilierten Graph als JSON inklusive Nodes, Edges und topologischer Reihenfolge.

### 3) Plan lesen

```bash
nova plan examples/hello_radar.ns
```

Das zeigt die menschlich lesbare Ausführungsplanung.

### 4) Graph visualisieren

```bash
nova graph examples/hello_radar.ns
```

Ausgabe ist ein DOT-Graph (`digraph nova { ... }`), den du mit Graphviz rendern kannst.

### 5) Ausführen

```bash
nova run examples/hello_radar.ns
```

Die Runtime führt Flows aus, dispatched Events und liefert strukturierte Ergebnisdaten.

---

## Grundbausteine der Sprache

Nova unterstützt aktuell diese Deklarationen:

- `system`
- `agent`
- `dataset`
- `tool`
- `sensor`
- `memory`
- `mesh`
- `flow`
- `event`

### Allgemeine Blockform

```ns
keyword NAME {
key: value
}
```

### `agent`

Definiert einen AI-Agenten (Modell, optional Tools, Embeddings-Backend):

```ns
agent researcher {
model: llama3
embeddings: atheria
tools: fetcher, summarizer
}
```

### `dataset`

Beschreibt Datenquelle(n):

```ns
dataset tech_rss {
source: rss
url: https://example.com/rss
}
```

### `tool`

Beschreibt verfügbare externe oder interne Capability:

```ns
tool summarizer {
backend: llm
}
```

### `sensor`

Repräsentiert einen Signallieferanten (periodisch/extern):

```ns
sensor market_watch {
kind: rss
interval: 60
}
```

### `memory`

Deklariert langlebige Wissens-/Kontextspeicher:

```ns
memory long_term {
backend: atheria
}
```

### `mesh`

Konfiguriert Worker-Kapazität oder Verteilung:

```ns
mesh cluster_a {
workers: 4
}
```

### `flow`

Definiert den Pipeline-Graph als Schritte:

```ns
flow radar {
rss.fetch tech_rss
atheria.embed tech_rss
researcher summarize tech_rss
emit dataset.updated tech_rss
}
```

### `event`

Verknüpft Trigger mit Flow-Aktionen:

```ns
event refresh {
on dataset.updated
do radar
}
```

---

## Flow-Design und Ausführungsgraph

### Schritt-Syntax

Ein Flow-Step ist im Kern eine Zeile. Typische Formen:

1. **Namespaced Task**
   ```text
   rss.fetch tech_rss
   ```
2. **Agent Task**
   ```text
   researcher summarize tech_rss
   ```
3. **Event Emission**
   ```text
   emit dataset.updated tech_rss
   ```

### Wie daraus ein DAG entsteht

Der Compiler erzeugt:

- Nodes für Deklarationen (`agent:researcher`, `flow:radar`, ...)
- Edges aus Step-Referenzen (`agent:researcher -> flow:radar`)
- Trigger-Edges aus Events (`event:refresh -> flow:radar`)

### Determinismus

Bei identischem Programm + identischer Konfiguration liefert Nova:

- gleiche Topologie,
- gleiche topologische Reihenfolge,
- reproduzierbare Ausführungsplanung.

---

## Events und reaktive Orchestrierung

Nova Events sind Topic-basiert.

### Typischer Ablauf

1. Flow emittiert `dataset.updated`
2. Event-Regel `on dataset.updated` greift
3. Zugeordneter Flow startet

### Rekursion und Schutz

Bei event-getriggerter Re-Entrancy (z. B. Flow triggert direkt denselben Flow erneut) schützt die Runtime durch einen Active-Flow-Guard, um Endlosschleifen zu verhindern.

---

## Memory, Sensoren und Mesh

### Memory

Nutze `memory`, um deklarativ klarzumachen, dass ein System persistente oder vektorbasierte Zustände nutzt.

### Sensoren

`sensor` ist der deklarative Einstieg für externe Signale (Feeds, Ticker, API-Puls, etc.).

### Mesh

`mesh` beschreibt verteilte Ausführungskapazität. Namespaced Steps (`rss.fetch`, `atheria.embed`, `gpu.vectorize`) können über den Mesh-Executor auf Worker geroutet werden.

---

## CLI-Toolchain (`nova`)

### `nova build <file.ns>`

- parst das Programm,
- validiert Regeln,
- kompiliert DAG,
- gibt JSON-Artefakt aus.

### `nova plan <file.ns>`

- zeigt menschenlesbaren Ausführungsplan,
- ideal für Reviews und Architekturabnahmen.

### `nova graph <file.ns>`

- erzeugt DOT/Graphviz-Text,
- nützlich für Architekturvisualisierung.

### `nova run <file.ns>`

- lädt Programm,
- plant Schedule,
- führt Flows aus,
- liefert strukturierte Runtime-Ergebnisse.

---

## Debugging, Fehlerbilder und Validierung

### Parse-Fehler

Typisch:

- fehlende `{` oder `}`,
- ungültiger Header,
- Property ohne `:`.

Nova liefert line-aware Fehlermeldungen (`line`, optional `col`).

### Validation-Fehler

Typisch:

- `agent` ohne `model`,
- `dataset` ohne `source`,
- `flow` ohne steps,
- `event` ohne `on` / `do`,
- unbekannte Symbolreferenzen in Flows.

### Runtime-Fehler

Typisch:

- nicht verfügbare Backends,
- fehlende externe Tools,
- Integrationsfehler in mesh/AI-Komponenten.

### Praktischer Workflow

1. `nova build` (statisch prüfen)
2. `nova plan` (Semantik verstehen)
3. `nova graph` (Topologie prüfen)
4. `nova run` (Runtime verifizieren)

---

## Projektstruktur und Best Practices

Empfohlene Struktur:

```text
project/
  nova/
    parser/
    compiler/
    runtime/
    graph/
    agents/
    events/
    mesh/
  nova_std/
  docs/
  examples/
  tests/
```

### Best Practices

1. **Ein Flow = ein klares Ziel** (z. B. ingest, enrich, summarize)
2. **Events sparsam und präzise benennen** (`dataset.updated`, nicht `something.happened`)
3. **Deklarationen klein halten** (Unix-Prinzip, Single Responsibility)
4. **Explizite Namen nutzen** (`researcher`, `market_memory`, `cluster_a`)
5. **Früh validieren** (`nova build` im CI)
6. **Graphen reviewen** (`nova graph` als Architektur-Artifact)

---

## Patterns für produktive AI-Systeme

### Pattern 1: Ingest -> Embed -> Agent

```ns
flow ingest_pipeline {
rss.fetch tech_rss
atheria.embed tech_rss
researcher summarize tech_rss
}
```

### Pattern 2: Event-getriebene Aktualisierung

```ns
event refresh_on_update {
on dataset.updated
do ingest_pipeline
}
```

### Pattern 3: Mesh-Offloading für rechenintensive Steps

```ns
mesh cluster_a {
workers: 8
}

flow heavy_compute {
gpu.vectorize corpus_a
wasm.score corpus_a
}
```

### Pattern 4: Wissenspersistenz

```ns
memory long_term {
backend: atheria
}
```

---

## FAQ

### Ist Nova eine "Skriptsprache"?

Nein. Nova ist deklarativ und modelliert Systeme. Die Runtime übersetzt diese Beschreibung in einen Ausführungsgraphen.

### Kann ich imperative Logik einbetten?

Indirekt über Tools/Backends. Die Nova-Sprache selbst bleibt bewusst deklarativ.

### Wie erweitere ich Nova?

Über neue Deklarationstypen (Parser/AST), neue Compiler-Regeln und neue Runtime-Handler.

### Wie bleibt das System wartbar?

Durch klare Blockgrenzen, deklarative Trennung, standardisierte Event-Namen und CI-Validierung.

---

## Von Nova-Shell zu Nova Language: Migrationshinweise

Wenn du aus bestehender `nova-shell`-Nutzung kommst:

1. Extrahiere wiederverwendbare Komponenten als `agent`, `dataset`, `tool`.
2. Modelliere Befehlssequenzen als `flow`.
3. Ersetze implizite Triggerlogik durch `event`-Regeln.
4. Definiere Skalierung explizit mit `mesh`.
5. Plane persistentes Kontextwissen über `memory`.

Zielbild: **weniger ad-hoc REPL-Orchestrierung, mehr versionierte Systemdefinition in `.ns`.**

---

## Nächste Schritte

- Lies ergänzend die formale Referenz in `docs/Nova_Language_Specification.md`.
- Starte mit `examples/tech_radar.ns`.
- Lege für jedes neue System zuerst ein kleines `nova plan`-review an.
- Nutze Tests (`tests/test_nova_*.py`) als Blaupause für eigene CI-Checks.

Viel Erfolg beim Bauen deklarativer AI-Systeme mit Nova.

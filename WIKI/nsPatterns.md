# nsPatterns

## Zweck

Diese Seite zeigt gute und schlechte Muster fuer Nova-Language-Programme.
Sie ist nicht die reine Syntaxreferenz, sondern ein Leitfaden fuer Struktur, Lesbarkeit, Wartbarkeit und sinnvolle Zerlegung groesserer `.ns`-Programme.

Wenn du die Sprache erst lernen willst, beginne mit [nsCreate](./nsCreate.md).
Wenn du nur Syntax nachschlagen willst, lies [nsReference](./nsReference.md).
Wenn du ausfuehrbare Architektur- und Entscheidungsblaupausen suchst, lies auch [DecisionPatterns](./DecisionPatterns.md).
Wenn du die formale AST-, Graph- und Ausfuehrungssemantik suchst, lies auch
[NovaSemantics](./NovaSemantics.md).

## Gute Grundmuster

## Muster 1: klarer Aufbau

Ein gutes `.ns`-Programm trennt Grundkontext, Ressourcen und aktive Logik:

```ns
system local_control {
  mode: local
}

state research_memory {
  namespace: market_radar
}

agent researcher {
  model: llama3
  memory: research_memory
}

dataset tech_rss {
  source: rss
  path: sample_news.json
}

flow radar {
  rss.fetch tech_rss -> fresh_news
  researcher summarize tech_rss -> briefing
}
```

Warum gut:

- erst Kontext
- dann Daten und Akteure
- dann Ausfuehrung

## Muster 2: Zwischenergebnisse benennen

```ns
flow enrich {
  rss.fetch tech_rss -> fetched
  atheria.embed tech_rss -> embedded
  researcher summarize tech_rss -> summary
}
```

Warum gut:

- Aliase machen den Ablauf lesbar
- Debugging und Graph-Verstaendnis werden einfacher

## Muster 3: Reaktive Programme mit `event`

```ns
event new_information {
  on: new_information
  flow: radar
}
```

Warum gut:

- Reaktivitaet ist explizit dokumentiert
- Flow und Trigger sind klar gekoppelt

## Muster 4: Dateien aufteilen

```ns
import "systems/local.ns"
import "datasets/news.ns"
import "agents/research.ns"
import "flows/radar.ns"
```

Warum gut:

- Programme wachsen modular
- Wiederverwendung wird einfacher

## Muster 5: Plattformaspekte nur dort nutzen, wo sie wirklich gebraucht werden

```ns
system control_plane {
  mode: mesh
  tenant: ops
}

service backend {
  package: base_sdk
  replicas: 2
}
```

Warum gut:

- Plattformlogik ist sichtbar
- einfache Flows werden nicht mit unnötiger Komplexitaet belastet

## Schlechte Muster

## Anti-Muster 1: alles in einen einzigen Flow werfen

```ns
flow giant_flow {
  rss.fetch tech_rss -> x1
  atheria.embed tech_rss -> x2
  researcher summarize tech_rss -> x3
  reviewer critique tech_rss -> x4
  system.log x4
  event.emit done x4
}
```

Warum schlecht:

- keine semantischen Zwischenstufen
- schlecht teilbar
- schwer testbar

Besser:

- Zwischenschritte sinnvoll benennen
- grosse Flows in mehrere kleinere Flows oder Tools zerlegen

## Anti-Muster 2: kryptische Namen

```ns
agent a1 {
  model: llama3
}

dataset d1 {
  source: rss
}
```

Warum schlecht:

- spaetere Pflege wird unnoetig schwer
- Graph und Doku verlieren an Lesbarkeit

Besser:

```ns
agent researcher {
  model: llama3
}

dataset tech_rss {
  source: rss
}
```

## Anti-Muster 3: `system` fuer alles verwenden

Wenn jeder Aspekt einer Datei in `system` gequetscht wird, wird das Modell unklar.

Besser:

- `system` nur fuer Laufzeit-, Tenant-, Policy- oder Placement-Kontext
- `state` fuer Zustand
- `agent`, `dataset`, `tool`, `service` fuer ihre jeweilige Rolle

## Anti-Muster 4: zu frueh Plattformkomplexitaet einbauen

Nicht jedes erste Beispiel braucht sofort:

- `service`
- `package`
- `tenant`
- `selector`
- `require_tls`

Besser:

1. erst lokal korrekt
2. dann modular
3. dann verteilt
4. dann plattformweit

## Anti-Muster 5: `ns.run` ohne `ns.graph`

Direkt auszufuehren ist moeglich, aber als Arbeitsweise schwach.

Besser:

```powershell
ns.graph datei.ns
ns.run datei.ns
```

## Strukturmuster fuer wachsende Programme

## Klein

Eine Datei:

```text
hello.ns
```

Geeignet fuer:

- Lernen
- Mini-Beispiele
- erste Experimente

## Mittel

Mehrere Dateien:

```text
systems/
agents/
datasets/
flows/
main.ns
```

Geeignet fuer:

- wiederverwendbare Projektbeispiele
- saubere Trennung von Rollen

## Gross

Zusatzlich:

```text
services/
packages/
tests/
```

Geeignet fuer:

- plattformnahe Workflows
- Service- und Package-Definitionen
- umfangreiche Programme mit mehreren Flows

## Empfohlener Schreibworkflow

1. Datei klein beginnen
2. Namen sauber waehlen
3. `ns.graph` benutzen
4. `ns.format` und `ns.lint` laufen lassen
5. erst dann `ns.run`
6. bei Wachstum per `import` zerlegen

## Typische Muster nach Ziel

### Daten plus Agent

- `dataset`
- `agent`
- `flow`

### Reaktive Automation

- `flow`
- `event`
- `state`

### Plattformprogramm

- `system`
- `tool`
- `service`
- `package`
- `flow`

## Verwandte Seiten

- [nsCreate](./nsCreate.md)
- [nsReference](./nsReference.md)
- [ExamplesAndRecipes](./ExamplesAndRecipes.md)
- [NovaLanguage](./NovaLanguage.md)
- [ComponentModel](./ComponentModel.md)

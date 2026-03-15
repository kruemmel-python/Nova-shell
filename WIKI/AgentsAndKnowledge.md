# Agents And Knowledge

## Zweck

Diese Seite ordnet die AI- und Wissensschicht von Nova-shell als zusammenhaengendes System ein. Im Zentrum stehen Agenten, Prompt-Ausfuehrung, Memory, Tooling und Atheria als lokaler Wissenskern.

## Kernpunkte

- Agenten sind keine isolierten Chats, sondern Runtime-Objekte mit Provider, Modell, Prompt-Template und optionalem System-Prompt.
- Memory ist als semantischer Speicher mit Namespace- und Projekt-Scope gedacht und kann manuell oder aus Agentlaeufen befuellt werden.
- Atheria ist die lokale Knowledge-Schicht fuer Suche, Training, Chat, Sensorik und Evolutionspfade.
- Tools sind strukturierte, wiederverwendbare Operationen, die aus Shell-, Agent- und Flow-Kontexten aufgerufen werden koennen.

## Praktische Nutzung

- Nutze `ai config`, um den aktiven Providerpfad zu validieren, bevor du Agenten anlegst.
- Nutze `memory namespace` und `memory project`, bevor du Eintraege einbettest.
- Nutze `atheria status` und `atheria init`, wenn Wissens- und Trainingspfade lokal laufen sollen.
- Nutze `tool register` fuer stabile, schema-validierte Operationen statt Ad-hoc-Shellstrings.

## Testbare Einstiege

### Memory und Atheria zusammen pruefen

```powershell
atheria status
atheria init
memory namespace docs
memory project ai
memory embed --id agent_core "Nova-shell verbindet CLI, Runtime und AI-OS."
memory search "AI-OS Runtime"
```

Erwartung:

- `atheria init` meldet einen lauffaehigen lokalen Kern oder einen klaren Fehlerzustand.
- `memory search` liefert Treffer mit Scope-Metadaten und Score.

### Werkzeug und Agent kombinieren

```powershell
tool register greet --description "Greet user" --schema "{\"type\":\"object\",\"properties\":{\"name\":{\"type\":\"string\"}},\"required\":[\"name\"]}" --pipeline "py \"Hello \" + {{py:name}}"
agent create helper "Nutze {{input}}" --provider lmstudio --model local-model
agent show helper
```

Erwartung:

- Das Tool ist danach ueber `tool call greet name=Nova` direkt nutzbar.
- Der Agent besitzt eine persistente Definition mit Provider und Modell.

## Typische Fragen und Fehler

### `agent run` liefert keine Antwort

- Provider oder Modell sind nicht konfiguriert.
- Lokaler Modellserver oder API-Zugang fehlen.
- Pruefe `ai providers` und `ai config`.

### `memory search` findet nichts

- Namespace oder Projekt wurden gewechselt.
- Es wurden noch keine Eintraege eingebettet.
- Die Anfrage ist in einem anderen Scope gelandet.

## Verwandte Seiten

- [NovaAgents](./NovaAgents.md)
- [NovaMemory](./NovaMemory.md)
- [NovaTools](./NovaTools.md)
- [AIOSConcept](./AIOSConcept.md)
- [ExamplesAndRecipes](./ExamplesAndRecipes.md)

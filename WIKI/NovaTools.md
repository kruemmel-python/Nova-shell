# Nova Tools

## Zweck

Tools sind strukturierte, benannte Operationen mit Eingabeschema und Pipeline-Template. Sie sind der sauberste Weg, wiederverwendbare Shell-Operationen bereitzustellen.

## Kernpunkte

- Ein Tool besitzt Name, Beschreibung, Schema und Pipeline.
- Tools koennen direkt aus der Shell oder indirekt aus Agent- und Plannerpfaden genutzt werden.
- Tools bilden eine Schicht zwischen Promptlogik und konkreter Kommandokette.

## Praktische Nutzung

- Registriere kleine, stabile Operationen als Tool statt sie jedes Mal neu zu tippen.
- Halte Schemata eng, damit `tool call` frueh auf fehlende Argumente pruefen kann.

## Testbare Einstiege

### Ein Tool definieren und ausfuehren

```powershell
tool register greet --description "Greet user" --schema "{\"type\":\"object\",\"properties\":{\"name\":{\"type\":\"string\"}},\"required\":[\"name\"]}" --pipeline "py \"Hello \" + {{py:name}}"
tool call greet name=Nova
tool show greet
```

Erwartung:

- Der Aufruf liefert `Hello Nova`.
- Die Tooldefinition bleibt ueber `tool show` inspizierbar.

## Typische Fragen und Fehler

### `tool call` scheitert

- Ein Pflichtfeld im Schema fehlt.
- Die Pipeline ist syntaktisch fehlerhaft.
- Der Template-Platzhalter passt nicht zum Eingabenamen.

## Verwandte Seiten

- [NovaCLI](./NovaCLI.md)
- [NovaPlanner](./NovaPlanner.md)
- [AgentsAndKnowledge](./AgentsAndKnowledge.md)
- [ExamplesAndRecipes](./ExamplesAndRecipes.md)

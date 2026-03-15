# Nova Memory

## Zweck

Nova Memory ist die semantische Speicherschicht fuer Shell- und Agentpfade. Die Seite erklaert Scope, Embedding und Retrieval im Projektkontext.

## Kernpunkte

- Memory ist in Namespace und Projekt gegliedert.
- Eintraege koennen explizit, aus Dateien oder indirekt aus Agentlaeufen entstehen.
- Die Memory-Schicht ist lokal und leichtgewichtig genug fuer schnelle Iteration.
- Agenten und Atheria koennen Memory als Kontextquelle verwenden.

## Praktische Nutzung

- Setze Namespace und Projekt bewusst, bevor du Inhalte schreibst.
- Nutze `--file` und `--meta` fuer nachvollziehbare Einbettungen aus echten Artefakten.
- Nutze `memory status`, wenn du Scope-Fehler vermutest.

## Testbare Einstiege

### Scope und Retrieval pruefen

```powershell
memory namespace docs
memory project wiki
memory embed --id intro "Nova-shell ist eine deklarative Runtime mit CLI und Mesh."
memory search "Mesh Runtime"
```

Erwartung:

- Der Eintrag wird im aktiven Scope gespeichert.
- Die Suche liefert einen semantisch passenden Treffer.

## Typische Fragen und Fehler

### Treffer liegen im falschen Projekt

- Namespace oder Projekt wurden vor dem Embed nicht gesetzt.
- Es wurde mit `--all` oder in einem anderen Scope gesucht.

## Verwandte Seiten

- [AgentsAndKnowledge](./AgentsAndKnowledge.md)
- [NovaAgents](./NovaAgents.md)
- [ExamplesAndRecipes](./ExamplesAndRecipes.md)
- [ProgrammingWithNovaShell](./ProgrammingWithNovaShell.md)

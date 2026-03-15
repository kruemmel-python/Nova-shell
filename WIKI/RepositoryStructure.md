# Repository Structure

## Zweck

Diese Seite ordnet den Quellbaum von Nova-shell und zeigt, wo welche Verantwortung liegt.
Sie ist eine Orientierungsseite fuer Entwickler, Reviewer und Dokumentationsarbeit.

## Top-Level

```text
nova/
tests/
examples/
docs/
packaging/
scripts/
WIKI/
nova_shell.py
novascript.py
```

## Wichtige Bereiche

### `nova/parser`

Parser, AST und Sprachnahe Syntaxverarbeitung fuer `.ns`.

### `nova/graph`

Execution-Graph-Modell, Compiler und Knotenstrukturen.

### `nova/runtime`

Deklarative Runtime, Control Plane, Scheduling, Security, Operations und Service-nahe Plattformlogik.

### `nova/agents`

Agent Runtime, Provider-Pfade, Memory, Prompts, Evals und Tool-Sandboxing.

### `nova/mesh`

Verteilte Worker- und Remote-Ausfuehrung.

### `tests`

Unit-, Integrations- und Shell-nahe Tests.

### `scripts`

Build-, Release-, Packaging- und Upgrade-Helfer.

### `WIKI`

Projektinterne Langform-Dokumentation, Referenz- und Tutorialseiten.

## Praktischer Lesepfad

Wer eine neue Funktion verstehen will, sollte meist in dieser Reihenfolge lesen:

1. passende Wiki-Seite
2. Referenzseite in [CodeReferenceIndex](./CodeReferenceIndex.md)
3. Implementierung im passenden `nova/*`-Subsystem
4. zugehoerige Tests

## Verwandte Seiten

- [Subsystems](./Subsystems.md)
- [DevelopmentGuide](./DevelopmentGuide.md)
- [CodeReferenceIndex](./CodeReferenceIndex.md)

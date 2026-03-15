# Execution Model

## Zweck

Das Execution Model beschreibt den Weg von einer Eingabe bis zur Ausfuehrung in Shell- oder Declarative-Pfaden.

## Kernpunkte

- Shellbefehle laufen direkt ueber `NovaShell` und die zugeordneten Handler.
- Deklarative Programme durchlaufen Parser, AST, Graph-Compiler und Runtime.
- Queue, Event-Bus und Daemon koennen Ausfuehrung asynchron und wiederholbar machen.
- Snapshots und Replay machen den Laufzeitpfad durable.

## Praktische Nutzung

- Verstehe zuerst, ob du einen direkten Shellbefehl oder einen Graphlauf startest.
- Nutze `ns.status` und `ns.control status`, wenn die eigentliche Frage nicht Rechenergebnis, sondern Runtimezustand ist.

## Testbare Einstiege

### Direkter Shelllauf und deklarativer Lauf im Vergleich

```powershell
py 1 + 1
ns.exec values = sys printf "1\n2\n"; for v in values:;     py $v
```

Erwartung:

- Der erste Befehl laeuft direkt als Ausdruck.
- Der zweite Befehl wird ueber den NovaScript-Interpreter abgearbeitet.

## Typische Fragen und Fehler

### Unklarer Laufzeitpfad

- Wenn `.ns` und `ns.*` im Spiel sind, ist der deklarative Pfad relevant.
- Wenn einzelne Kommandos direkt aufgerufen werden, ist meist die Shell-Runtime gemeint.

## Verwandte Seiten

- [Architecture](./Architecture.md)
- [NovaRuntime](./NovaRuntime.md)
- [CLIAndLegacyRuntime](./CLIAndLegacyRuntime.md)
- [DataFlow](./DataFlow.md)

# Execution Model

## Kerngedanke

Nova-shell fuehrt deklarative Programme als Execution Graph aus.

## Pipeline

```text
Source
  ↓
Parser
  ↓
Typed AST
  ↓
Graph Compiler
  ↓
Execution Graph
  ↓
Runtime
```

## Eigenschaften

- topologische Ausfuehrung
- Flow-Schliessung statt Gesamtprogrammzwang
- Event-Bindings fuer neue Runs
- Queueing und Scheduling als externe Trigger
- persistente States und Replay

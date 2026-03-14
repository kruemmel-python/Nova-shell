# Nova AI Operating System Architecture

Nova-shell is evolved into a unified **AI operating system runtime and programming language** with three pillars:

1. **Nova Language (`.ns`)** for declarative definitions.
2. **AI Runtime** for agents, tools, and memory-aware execution.
3. **Distributed Mesh Runtime** for local/worker orchestration.

## Design decisions

- **Declarative-first model**: `agent`, `dataset`, `flow`, `event`, `tool`, `state`, and `system` blocks keep system intent explicit.
- **AST + Graph compilation**: programs parse into typed AST nodes, then compile to a DAG execution graph.
- **Event-driven orchestration**: events trigger flow execution through an in-process event bus.
- **Agent-native runtime**: agents expose model selection, tools, embeddings backend, memory, and task execution.
- **Mesh-ready execution**: steps route to local or registered workers based on capabilities.

## Runtime layers

- `nova/parser`: Nova language parser with structured errors.
- `nova/graph`: graph node/edge model, DAG checks, and compiler.
- `nova/agents`: generic agent runtime with tool injection and memory.
- `nova/events`: topic-based event bus.
- `nova/mesh`: worker registry and task routing.
- `nova/runtime`: orchestrator that loads programs, builds graphs, and runs flows.

## Directory structure

```text
nova/
  __init__.py
  ast.py
  parser/
    __init__.py
    parser.py
  graph/
    __init__.py
    engine.py
  agents/
    __init__.py
    runtime.py
  events/
    __init__.py
    bus.py
  mesh/
    __init__.py
    cluster.py
  runtime/
    __init__.py
    core.py
examples/
  tech_radar.ns
  distributed_pipeline.ns
tests/
  test_nova_language_runtime.py
```

## Nova language example

```ns
agent researcher {
model: llama3
}

dataset tech_rss {
source: rss
}

flow radar {
```
rss.fetch tech_rss
atheria.embed tech_rss
researcher summarize tech_rss
```
}

event refresh_on_update {
on dataset.updated
do radar
}
```

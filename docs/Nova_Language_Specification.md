# Nova Language Specification

Version: 0.1 (draft)

Nova is a declarative AI system programming language. Nova source files (`.ns`) describe architecture, capabilities, and execution relationships. Programs compile into deterministic execution DAGs.

## 1. Lexical Structure

- Encoding: UTF-8.
- Comments: lines starting with `#`.
- Identifiers: `[A-Za-z_][A-Za-z0-9_]*`.
- Block delimiters: `{` and `}`.
- Flow fence delimiter: triple backticks (` ``` `) for optional multi-line flow content.
- Property separator: `key: value`.

## 2. Grammar (EBNF)

```ebnf
program        = { declaration } ;
declaration    = agent_decl | dataset_decl | flow_decl | event_decl | sensor_decl
               | memory_decl | tool_decl | mesh_decl | system_decl ;

agent_decl     = "agent" identifier block_props ;
dataset_decl   = "dataset" identifier block_props ;
tool_decl      = "tool" identifier block_props ;
sensor_decl    = "sensor" identifier block_props ;
memory_decl    = "memory" identifier block_props ;
mesh_decl      = "mesh" identifier block_props ;
system_decl    = "system" identifier block_props ;

flow_decl      = "flow" identifier "{" flow_body "}" ;
flow_body      = ["```"] { flow_step } ["```"] ;
flow_step      = line ;

event_decl     = "event" identifier "{" "on" line { "do" identifier } "}" ;

block_props    = "{" { property } "}" ;
property       = identifier ":" value ;
value          = line ;
```

## 3. Semantic Model

### 3.1 Core blocks

- `agent`: LLM-backed execution unit with model and tool configuration.
- `dataset`: structured data source (RSS/CSV/files/API).
- `flow`: DAG-oriented pipeline with symbolic steps.
- `event`: reactive rule mapping trigger topic to one or more flow activations.
- `sensor`: external/periodic signal source.
- `memory`: long-lived or vectorized memory store.
- `tool`: external capability invocation surface.
- `mesh`: distributed worker topology and scheduling hints.
- `system`: global runtime policies.

### 3.2 Execution model

Compilation pipeline:

`Nova Script (.ns) -> Lexer -> Parser -> AST -> Graph Compiler -> Execution DAG -> Runtime Scheduler`

- AST declarations are normalized into node types.
- Dependencies are inferred from flow step references and event actions.
- Runtime executes a topologically sorted schedule.
- Event topics may trigger additional flows; runtime must avoid non-terminating recursion.

## 4. Validation Rules

Required baseline rules:

1. `agent` must define `model`.
2. `dataset` must define `source`.
3. `flow` must define at least one step.
4. `event` must define one `on` trigger and at least one `do` action.
5. flow heads that reference declarations must resolve to declared symbols.
6. resulting execution graph must be acyclic.

## 5. Error Model

Compiler and runtime errors are structured and location-aware when possible.

- **Lexing errors**: malformed token boundaries.
- **Parsing errors**: block/header/body structural violations.
- **Validation errors**: missing required properties, unknown references, illegal graph dependencies.
- **Runtime errors**: execution backend failures, missing capabilities, external tool errors.

Error messages should include:

- category (`parse`, `validate`, `runtime`)
- source location (`line`, optionally `column`)
- actionable message

## 6. Dependency Resolution

Dependency edges are produced from:

- flow step heads (`agent`, `dataset`, `tool`, `sensor`, `memory`, `mesh` namespaces)
- event action targets (`event -> flow`)

Resolution priority:

1. explicit namespace token (`dataset.foo`)
2. implicit declaration name (`foo` -> `agent:foo`/`dataset:foo`/...)

## 7. Runtime Guarantees

- Deterministic schedule for unchanged source and configuration.
- DAG safety (compile-time cycle rejection).
- Event re-entry protection to prevent infinite recursive flow activation.
- Pluggable runtime backends for local and mesh execution.
- Extensibility via new declaration types and namespaced step handlers.

## 8. Example

```ns
agent researcher {
  model: llama3
}

dataset tech_rss {
  source: rss
  url: https://example.com/rss
}

sensor trend_watch {
  kind: rss
}

memory market_memory {
  backend: atheria
}

flow radar {
  rss.fetch tech_rss
  atheria.embed tech_rss
  researcher summarize tech_rss
}

event refresh_on_update {
  on dataset.updated
  do radar
}
```

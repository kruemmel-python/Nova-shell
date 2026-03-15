# Nova Agents

## Zweck

Agenten sind in Nova-shell deklarierte, wiederverwendbare Laufzeitobjekte mit:

- Provider- und Modellauswahl
- Tool-Freigaben
- Memory-Scope
- Prompt-Versionen
- Governance
- Evaluationen

## Kernobjekte

| Klasse | Rolle |
| --- | --- |
| `AgentSpecification` | statische Beschreibung eines Agenten |
| `AgentTask` | auszufuehrende Aufgabe |
| `AgentExecutionResult` | Ergebniscontainer |
| `AgentRuntime` | Registrierung und Ausfuehrung |
| `PromptRegistry` | Prompt-Versionen |
| `DistributedMemoryStore` | Agent-Memory und Suche |
| `AgentEvalStore` | Auswertungsdaten |
| `ToolSandbox` | Tool-Freigabe und Governance |

## Methoden und Schnittstellen

`AgentRuntime`:

- `register(declaration)`
- `specification(name)`
- `execute(task, context)`

### Agent-Lebenszyklus

```text
Declaration
  ↓
AgentRuntime.register()
  ↓
AgentTask
  ↓
Governance
  ↓
Prompt Resolution
  ↓
Provider Invocation oder lokales Rendern
  ↓
Memory Write
  ↓
Evaluation
```

## CLI

Typische Agent-Kommandos:

- `agent create`
- `agent run`
- `agent graph create`
- `ai providers`

## API

Agent-relevante Control-Plane-Endpunkte:

- `/agents/prompts`
- `/agents/evals`
- `/agents/memory`

## Beispiele

```ns
agent reviewer {
  provider: openai
  model: gpt-4o-mini
  tools: [memory.search, system.log]
  memory: review
}
```

```text
agent create analyst "Summarize {{input}}"
agent run analyst quarterly report
agent graph create review_chain --nodes analyst,reviewer
```

## Verwandte Seiten

- [ClassReference](./ClassReference.md)
- [RuntimeMethodReference](./RuntimeMethodReference.md)
- [ExamplesAndRecipes](./ExamplesAndRecipes.md)
- [PageTemplate](./PageTemplate.md)

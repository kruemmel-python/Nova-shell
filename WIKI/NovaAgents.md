# Nova Agents

## Zweck

Agenten sind in Nova-shell deklarierte, wiederverwendbare Laufzeitobjekte mit Provider- und Modellauswahl, Tool-Freigaben, Memory-Scope, Prompt-Versionen, Governance und Evaluationen.

## Kernobjekte

| Klasse | Rolle |
| --- | --- |
| `AgentSpecification` | statische Beschreibung eines Agenten |
| `AgentTask` | auszufuehrende Aufgabe |
| `AgentExecutionResult` | Ergebniscontainer |
| `AgentRuntime` | Registrierung, Aufloesung und Ausfuehrung |
| `PromptRegistry` | Verwaltung von Prompt-Versionen |
| `DistributedMemoryStore` | Agent-Memory und Suche |
| `AgentEvalStore` | Auswertungsdaten und Bewertungsartefakte |
| `ToolSandbox` | Tool-Freigabe, Begrenzung und Governance |

## Agent-Lebenszyklus

```text
Declaration
  ->
AgentRuntime.register()
  ->
AgentTask
  ->
Governance
  ->
Prompt Resolution
  ->
Provider Invocation oder lokales Rendern
  ->
Memory Write
  ->
Evaluation
```

## Methoden und Schnittstellen

Wichtige `AgentRuntime`-Schnittstellen:

- `register(declaration)`
- `specification(name)`
- `execute(task, context)`

Wichtige Agentenfelder in `.ns`:

- `provider`
- `providers`
- `model`
- `tools`
- `memory`
- `system_prompt`
- `prompts`
- `prompt_version`
- `governance`

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

## Testbare Beispiele

### Deklarativer Agent

```ns
agent reviewer {
  provider: openai
  model: gpt-4o-mini
  tools: [memory.search, system.log]
  memory: review
}
```

### CLI-Beispiel

```text
agent create analyst "Summarize {{input}}"
agent run analyst quarterly report
agent graph create review_chain --nodes analyst,reviewer
```

### Python-Beispiel

```python
from nova.agents.runtime import AgentRuntime, AgentSpecification, AgentTask

agents = AgentRuntime()
agents.register(
    AgentSpecification(
        name="researcher",
        model="gpt-4o-mini",
        tools=["system.log"],
    )
)

result = agents.execute(
    AgentTask(
        agent="researcher",
        objective="Summarize the current dataset",
    )
)
print(result.output)
```

## Typische Fehler und Fragen

### Warum antwortet ein Agent anders als erwartet?

Dann muessen meist Prompt-Version, Providerwahl, Governance oder Tool-Freigaben geprueft werden.

### Wo landet Agent-Memory?

Im konfigurierten Memory-Scope oder Namespace, nicht als loses Nebenprodukt.

### Woran erkenne ich, ob ein Agent lokal oder extern arbeitet?

An Provider, Modell und Runtime-Kontext.

## Verwandte Seiten

- [AgentsAndKnowledge](./AgentsAndKnowledge.md)
- [NovaMemory](./NovaMemory.md)
- [NovaTools](./NovaTools.md)
- [RuntimeMethodReference](./RuntimeMethodReference.md)
- [ExamplesAndRecipes](./ExamplesAndRecipes.md)

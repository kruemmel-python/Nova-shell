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
| `MyceliaAtheriaCoEvolutionLab` | populationsbezogene Co-Evolution ueber Forecast- und Kruemmungssignale |
| `AtheriaALSRuntime` | residenter Atheria-Live-Pfad mit Dialog, Triggern und Voice |

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

## Co-Evolution mit Mycelia und Atheria

Nova-shell fuehrt Agenten nicht nur einzeln aus.
Mit der Co-Evolution-Schicht koennen Populationen ueber mehrere Signale optimiert werden:

- Forecast-Qualitaet
- Atheria-Invarianten
- Tool-Erfolgsraten
- geometrische Komplexitaet

CLI:

```powershell
mycelia coevolve run research-pop --cycles 5 --input "edge inference pressure rises"
mycelia coevolve status research-pop
mycelia population tick research-pop --cycles 5 --coevolve
```

## ALS als dauerhafte Atheria-Instanz

ALS ist kein einzelner Agent, aber es verhaelt sich aus Plattformsicht wie eine
laufende kognitive Instanz:

- permanenter Stream-Zustand
- lokale Wissensintegration
- belegbare Dialoge
- Voice als First-Class-Ausgang

Es ist damit die Bruecke zwischen klassischer Agent-Ausfuehrung und einer
dauerhaft existierenden Atheria-Praesenz.

CLI:

```powershell
atheria als start
atheria als ask "Was ist die aktuelle Hypothese?"
atheria als feedback "Verfolge Supply-Chain-Risiken strenger."
```

## CLI

Typische Agent-Kommandos:

- `agent create`
- `agent run`
- `agent graph create`
- `ai providers`

Wichtig fuer deklarative Agenten:

- `ns.run` laedt nicht nur Flows und Events, sondern exportiert deklarative `agent { ... }`-Bloecke jetzt direkt in die Shell-Agentenwelt
- dadurch koennen Agenten aus einer geladenen `.ns`-Datei sofort ueber `agent list` und `agent run` genutzt werden
- fuer generierte standalone Agenten aus Skill-Daten siehe [StandaloneSkillAgents](./StandaloneSkillAgents.md)

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

### Deklarative Agenten aus `.ns`

```powershell
ns.run .\examples\react_best_practices_agents.ns
agent list
agent run react_best_practices_async_parallel "const user = await fetchUser(); const posts = await fetchPosts();"
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

### Co-Evolution ueber die CLI

```powershell
mycelia coevolve run trend-rss --cycles 3 --input "news feeds with predictive relevance"
mycelia coevolve status trend-rss
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
- [MyceliaAtheriaCoEvolution](./MyceliaAtheriaCoEvolution.md)
- [AtheriaContinuousEvolutionAndLiveStream](./AtheriaContinuousEvolutionAndLiveStream.md)
- [AtheriaVoice](./AtheriaVoice.md)
- [RuntimeMethodReference](./RuntimeMethodReference.md)
- [ExamplesAndRecipes](./ExamplesAndRecipes.md)

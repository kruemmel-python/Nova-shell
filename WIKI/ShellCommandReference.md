# Shell Command Reference

## Zweck

Diese Seite verbindet die sichtbaren CLI-Kommandos mit den internen Handlern in `NovaShell`.
Sie ist fuer Entwickler wichtig, die nicht nur Befehle benutzen, sondern verstehen wollen:

- welcher Handler ein Kommando ausfuehrt
- welche Rueckgabeform zu erwarten ist
- welche Kommandos lokal testbar sind
- wann ein Kommando Shell-, Agenten- oder Runtime-Zustand veraendert

## Kernobjekte

- `NovaShell.route`
- `NovaShell._route_internal`
- `NovaShell._route_single`
- `NovaShell._execute_stage`
- `CommandResult`

## Ausfuehrungsmodell

Der Shell-Pfad sieht vereinfacht so aus:

```text
text command
  ->
NovaShell.route(...)
  ->
command parsing
  ->
top-level handler such as _run_ai or _ns_run
  ->
CommandResult(output, error, data, data_type)
```

Wenn du wissen willst, was ein Kommando tut, suchst du den zugehoerigen Handler.
Wenn du verstehen willst, wie Pipelines funktionieren, suchst du `route`, `_split_pipeline`, `_execute_stage`.

## Rueckgabeform

Die meisten Kommandos laufen am Ende auf `CommandResult` hinaus.
Praktisch bedeutet das:

- `output` ist der sichtbare Text
- `error` enthaelt eine Fehlerbeschreibung
- `data` kann strukturierte Daten tragen
- `data_type` beschreibt grob, wie `data` zu interpretieren ist

Fuer Shell-Arbeit ist `output` relevant, fuer Integrationen und Tests oft `data`.

## Kommandofamilien

### Basis- und Shell-Kommandos

| Kommando | Handler | Typisches Ergebnis |
| --- | --- | --- |
| `doctor` | `_doctor` | Textstatus der Installation |
| `help` | `_help` | Textliste aller Kommandos |
| `cd` | `_cd` | Arbeitsverzeichnis wird geaendert |
| `pwd` | `_pwd` | aktuelles Arbeitsverzeichnis |
| `clear`, `cls` | `_clear_console` | Konsole wird geleert |
| `watch` | `_watch` | Beobachtungs- oder Pollinglauf |
| `events` | `_events` | Eventuebersicht |
| `wiki` | `_run_wiki` | JSON mit Build-, Open- oder Serverstatus |

### Compute

| Kommando | Handler | Testbarer Einstieg |
| --- | --- | --- |
| `py` | `_run_python` | `py 1 + 1` |
| `cpp` | `_run_cpp` | `cpp 1 + 1` |
| `cpp.sandbox` | `_run_cpp_sandbox` | `cpp.sandbox int main(){ return 0; }` |
| `cpp.expr` | `_run_cpp_expr` | `cpp.expr x + 1` |
| `cpp.expr_chain` | `_run_cpp_expr_chain` | `cpp.expr_chain x+1 ; x*2` |
| `gpu` | `_run_gpu` | `gpu graph show` |
| `wasm` | `_run_wasm` | `wasm .\module.wasm` |
| `jit_wasm` | `_run_jit_wasm` | `jit_wasm 1 + 2 * 3` |
| `sys` | `_run_system` | `sys echo hello` |
| `data` | `_run_data` | `data load sample.csv` |
| `data.load` | `_run_data_load` | `data.load sample.csv` |

### AI, Memory und Tools

| Kommando | Handler | Testbarer Einstieg |
| --- | --- | --- |
| `ai` | `_run_ai` | `ai providers` |
| `atheria` | `_run_atheria` | `atheria status` |
| `agent` | `_run_agent` | `agent list` |
| `memory` | `_run_memory` | `memory status` |
| `tool` | `_run_tool` | `tool list` |
| `event` | `_run_event` | `event emit ping now` |

### Plattform und Runtime

| Kommando | Handler | Testbarer Einstieg |
| --- | --- | --- |
| `mesh` | `_run_mesh` | `mesh list` |
| `lens` | `_run_lens` | `lens last` |
| `synth` | `_run_synth` | `synth forecast` |
| `remote` | `_run_remote` | `remote http://127.0.0.1:8766 py 1 + 1` |
| `vision` | `_run_vision` | `vision status` |
| `guard` | `_run_guard` | `guard list` |
| `secure` | `_run_secure` | Security- oder Trust-Pfad |
| `flow` | `_run_flow` | Flow-Utilities |
| `observe` | `_run_observe` | Beobachtung und Status |
| `studio` | `_run_studio` | Studio- oder UI-Pfad |

### Deklarative Runtime

| Kommando | Handler | Testbarer Einstieg |
| --- | --- | --- |
| `ns.exec` | `_ns_exec` | `ns.exec py 1 + 1` |
| `ns.run` | `_ns_run` | `ns.run .\control.ns` |
| `ns.graph` | `_ns_graph` | `ns.graph .\control.ns` |
| `ns.status` | `_ns_status` | `ns.status` |
| `ns.cluster` | `_ns_cluster` | Clusterverwaltung |
| `ns.auth` | `_ns_auth` | Auth- und Tenantverwaltung |
| `ns.deploy` | `_ns_deploy` | Rollout und Deployment |
| `ns.recover` | `_ns_recover` | Recovery und Playbooks |
| `ns.control` | `_ns_control` | Queue, Scheduler, API, Metrics |
| `ns.snapshot` | `_ns_snapshot` | `ns.snapshot .\snap.json` |
| `ns.resume` | `_ns_resume` | `ns.resume .\snap.json` |

## Testbare Pfade

### Pfad 1: von Shell-Ausdruck zu Tool

```powershell
py "Hello " + "Nova"
tool register greet --description "Greet user" --schema "{\"type\":\"object\",\"properties\":{\"name\":{\"type\":\"string\"}},\"required\":[\"name\"]}" --pipeline "py \"Hello \" + {{py:name}}"
tool call greet name=Nova
```

Interne Handler:

- `_run_python`
- `_run_tool`
- `_render_tool_pipeline`
- `_parse_tool_call_payload`
- `_validate_tool_payload`

### Pfad 2: von Text zu Memory und Agent

```powershell
memory embed --id intro "Nova-shell combines runtime and AI."
memory search "runtime AI"
agent create helper "Summarize {{input}}" --provider lmstudio --model local-model
agent run helper "Nova-shell combines runtime and AI."
```

Interne Handler:

- `_run_memory`
- `_resolve_memory_scope`
- `_run_agent`
- `_render_agent_prompt`
- `_run_agent_once`

### Pfad 3: von Datei zu deklarativer Runtime

```powershell
ns.graph .\control.ns
ns.run .\control.ns
ns.control status
```

Interne Handler:

- `_ns_graph`
- `_ns_run`
- `_ns_control`
- `_active_declarative_runtime`
- `_require_declarative_access`

### Pfad 4: von Telemetrie zu Predictive Shift

```powershell
py 1 + 1
py 2 + 1
py 3 + 1
synth forecast
synth shift suggest "for item in rows: total += item"
```

Interne Handler und Objekte:

- `_run_python`
- `_execute_stage`
- `_run_synth`
- `NovaSynth.suggest`
- `PredictiveEngineShifter.forecast`
- `PredictiveEngineShifter.recommend_engine`

### Pfad 4b: von Shell-Stage zu Lens-Snapshot

```powershell
py 2 + 2
lens last
lens show <snapshot_id>
lens replay <snapshot_id>
```

Interne Handler und Objekte:

- `_run_python`
- `_execute_stage`
- `_run_lens`
- `NovaLensStore.record`
- `NovaLensStore.get`
- `NovaLensStore.replay`

Der wichtige Punkt fuer Entwickler ist:
Nach der Stage landet nicht nur Text auf dem Bildschirm, sondern auch ein
persistenter Snapshot in `.nova_lens/lineage.db` plus referenzierte Inhalte in
`.nova_lens/cas`.

Die Speicherschicht dahinter ist in [NovaLens](./NovaLens.md) erklaert.

### Pfad 5: von Invariante zu Federated Mesh Broadcast

```powershell
mesh federated publish --statement "Shared invariant" --namespace swarm --project lab --broadcast
```

Interne Handler und Objekte:

- `_run_mesh`
- `FederatedLearningMesh.publish_update`
- `FederatedLearningMesh.broadcast_update`
- `MeshWorkerServer`

### Pfad 6: von Population zu Co-Evolution

```powershell
mycelia coevolve run research-pop --cycles 2 --input "edge inference pressure rises"
```

Interne Handler und Objekte:

- `_run_mycelia`
- `_run_mycelia_population_cycles`
- `MyceliaAtheriaCoEvolutionLab.blend_score`
- `MyceliaAtheriaCoEvolutionLab.record_run`

## Pipeline-Programmierung

### Wichtige Methoden in `NovaShell`

- `_split_pipeline`
- `_build_pipeline_graph`
- `_execute_stage`
- `_parallel_stage`
- `_route_with_input`
- `_materialize_if_generator`

### Minimalbeispiel

```powershell
sys echo "Nova-shell" | py _.upper()
```

### Strukturierte Daten

```powershell
data load sample.csv | py len(_)
```

Hier ist `_` keine Zeichenkette, sondern eine strukturierte Datenmenge.

## Wie man einen Handler findet

Wenn du ein Kommando auf den Code zurueckfuehren willst:

1. suche in `nova_shell.py` nach `self.commands`
2. suche den Handlernamen wie `_run_ai` oder `_ns_run`
3. pruefe, ob Hilfsfunktionen wie `_render_agent_prompt` oder `_execute_stage` beteiligt sind

## Typische Diagnosefragen

### Welcher Handler ist aktiv?

Suche in `nova_shell.py` nach:

- `self.commands`
- dem Handlernamen wie `_run_ai`
- dem Kommando wie `ns.run`

### Warum kommt Text statt strukturierter Daten zurueck?

Dann liefert der Handler wahrscheinlich `output`, aber kein oder nur einfaches `data`.

### Warum veraendert ein Kommando globalen Zustand?

Weil einige Handler nicht nur lesen, sondern Memory, Tool-Registry, Agent-Definitionen, Runtime-Kontext oder Queue-Zustaende schreiben.

## Lesepfade

Wenn du:

- Kommandos benutzen willst: [NovaCLI](./NovaCLI.md)
- Shell intern verstehen willst: [ProgrammingWithNovaShell](./ProgrammingWithNovaShell.md)
- Symbole und Methoden suchen willst: [CodeReferenceIndex](./CodeReferenceIndex.md)
- Runtime-Methoden nachvollziehen willst: [RuntimeMethodReference](./RuntimeMethodReference.md)

## Verwandte Seiten

- [NovaCLI](./NovaCLI.md)
- [ProgrammingWithNovaShell](./ProgrammingWithNovaShell.md)
- [CodeReferenceIndex](./CodeReferenceIndex.md)
- [RuntimeMethodReference](./RuntimeMethodReference.md)
- [NovaSynthPredictiveEngineShifting](./NovaSynthPredictiveEngineShifting.md)
- [ZeroCopyFederatedLearningMesh](./ZeroCopyFederatedLearningMesh.md)
- [MyceliaAtheriaCoEvolution](./MyceliaAtheriaCoEvolution.md)
- [PageTemplate](./PageTemplate.md)

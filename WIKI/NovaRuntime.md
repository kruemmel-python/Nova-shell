# Nova Runtime

## Zweck

`NovaRuntime` ist die zentrale Laufzeit fuer deklarative `.ns`-Programme.
Sie laedt Programme, kompiliert Graphen, fuehrt Flows aus, emittiert Events und bindet Plattformdienste wie Queue, Control Plane, Services und Observability zusammen.

## Kernobjekte

| Objekt | Rolle |
| --- | --- |
| `NovaRuntime` | zentrale Laufzeitinstanz |
| `RuntimeContext` | gebuendelter Kontext fuer Agents, State, Control Plane, Security und Services |
| `CompiledNovaProgram` | geladene und kompilierte Programmdarstellung |
| `NovaRuntimeResult` | Ergebnis einer Programmausfuehrung |
| `BackendRouter` | Zuweisung von Ausfuehrungen auf passende lokale oder native Backends |
| `NovaLensStore` | Shell-Lineage mit Replay und content-addressable Speicherung |
| `DurableControlPlane` | Queue, Schedules, Replay und Status |
| `NovaControlPlaneAPIServer` | HTTP-API fuer die Plattform |
| `PredictiveEngineShifter` | forecast-basierte Engine-Wahl und delegierte Ausfuehrung |
| `AtheriaALSRuntime` | residenter Atheria-Live-Loop mit Chronik, Lens und Speech Acts |

## Lebenszyklus

```text
parse / load
  ->
compile
  ->
execute_flow / run / emit
  ->
state, events, services, traces
  ->
snapshot / resume / close
```

## Methoden und Schnittstellen

### Programm und Kontext

- `compile(source, source_name, base_path)`
- `load(program_or_source, source_name, base_path)`
- `run(program_or_source, flow, source_name, base_path)`
- `close()`

### Flow- und Eventausfuehrung

- `execute_flow(flow_name, trigger_event=None)`
- `emit(event_name, payload=None)`

### Snapshot und Wiederaufnahme

- `snapshot(file_path=None)`
- `resume(snapshot_or_path)`

### Scheduler und Control Plane

- `enqueue_flow(...)`
- `schedule_flow(...)`
- `schedule_event(...)`
- `scheduler_tick()`
- `run_pending_tasks(...)`

### API und Betrieb

- `start_control_api(...)`
- `stop_control_api()`
- `control_api_status()`
- `list_traces(...)`
- `list_alerts()`
- `export_metrics(...)`

### Services und Plattform

- `install_package(package_name)`
- `deploy_service(service_name, auto_promote=None)`
- `list_services()`
- `list_packages()`
- `discover_service(...)`
- `predictive.forecast()`
- `predictive.recommend_engine(...)`

### Residentes Atheria ALS

- `als.configure(...)`
- `als.status_payload()`
- `als.run_cycle(...)`
- `als.ask(...)`
- `als.feedback(...)`
- `als.voice_status()`
- `als.serve_forever(...)`

### Shell-Lineage und Replay

- `lens.record(...)` im klassischen Shell-Pfad
- `lens list`
- `lens show`
- `lens replay`
- `lens fork`

Auch wenn `NovaLensStore` nicht Teil der deklarativen `nova.runtime`-Klassen
ist, gehoert er zur realen Betriebsarchitektur von Nova-shell.
Er speichert Shell- und Monitor-Stufen persistent ueber `lineage.db` und einen
content-addressable Store in `.nova_lens/cas`.

Mit ALS gibt es jetzt einen zusaetzlichen residenten Atheria-Laufzeitpfad.
Er lebt unter `~/.nova_shell_memory/atheria_als/`, erzeugt kontinuierliche
Resonanzereignisse, schreibt eine lokale Aion-Chronik und persistiert Speech
Acts als Teil der Kausalspur.

## Eingebaute Toolpfade

Die Runtime kennt eingebaute Pfade, die in Flows direkt auftauchen koennen:

- `rss.fetch`
- `atheria.embed`
- `system.log`
- `event.emit`
- `flow.run`
- `state.set`
- `state.get`
- `service.deploy`
- `package.install`

## Atheria ALS

ALS ist die resident laufende Live-Form von Atheria in der Shell-Runtime.
Es verbindet:

- Feed-Ingestion
- Resonanz- und Triggerlogik
- Atheria-Training
- Lens-Snapshots
- Aion-Chronik
- Voice und Dialog

CLI:

```powershell
atheria als status
atheria als cycle
atheria als start
atheria als ask "Was dominiert den Stream?"
```

Die vertiefte Architektur steht in [AtheriaContinuousEvolutionAndLiveStream](./AtheriaContinuousEvolutionAndLiveStream.md).

## Predictive Shifting

Der Runtimepfad bindet den Predictive Engine Shifter direkt in Telemetrie und Engine-Delegation ein.

Dadurch kann Nova-shell:

- Stage-Ausfuehrungen als Telemetrie speichern
- Last- und Spannungsanstiege prognostizieren
- Zielpfade fuer `synth shift` aus Forecast und Heuristik gemeinsam ableiten

CLI:

```powershell
synth forecast
synth shift suggest "for item in rows: total += item"
synth shift run "for item in rows: total += item"
```

## CLI

Direkte Runtime-Kommandos:

- `ns.exec`
- `ns.run`
- `ns.graph`
- `ns.status`
- `ns.control`
- `ns.snapshot`
- `ns.resume`

## API

Die Runtime kann die HTTP-Control-Plane direkt bereitstellen:

- `start_control_api(...)`
- `stop_control_api()`
- `control_api_status()`
- `export_metrics(...)`

Details stehen in [APIReference](./APIReference.md).

## Testbare Beispiele

### Ein Programm aus Python laufen lassen

```python
from nova.runtime.runtime import NovaRuntime

source = """
agent helper {
  model: local
}

dataset notes {
  items: [{text: "hello"}]
}

flow boot {
  helper summarize notes -> summary
}
"""

with NovaRuntime() as runtime:
    result = runtime.run(source)
    print(result.context_snapshot)
```

### Ein bestehendes Beispiel ueber die CLI ausfuehren

```powershell
ns.graph examples\market_radar.ns
ns.run examples\market_radar.ns
ns.status
```

### Snapshot schreiben und laden

```powershell
ns.snapshot
ns.resume
```

### Predictive Shift live pruefen

```powershell
py 1 + 1
py 2 + 1
py 3 + 1
synth forecast
synth shift suggest "matrix multiply tensor embedding"
```

### Lens im klassischen Shell-Pfad pruefen

```powershell
py 2 + 2
lens last
```

Wenn du nachvollziehen willst, wie `.nova_lens/lineage.db` und `.nova_lens/cas`
zusammenarbeiten, lies [NovaLens](./NovaLens.md).

## Typische Fehler und Fragen

### Wann ist ein Problem ein Parser- und wann ein Runtime-Problem?

Wenn `ns.graph` funktioniert, aber `ns.run` nicht, ist die Syntax meist korrekt und der Fehler liegt spaeter im Laufzeitpfad.

### Wo fuehrt die Runtime Agenten aus?

Nicht isoliert von allem anderen, sondern im `RuntimeContext` zusammen mit State, Events, Services und Mesh.

### Wo beginnt man bei Plattformfehlern?

Mit `ns.status`, `ns.control` und den API- oder Trace-Pfaden.

## Verwandte Seiten

- [RuntimeMethodReference](./RuntimeMethodReference.md)
- [NovaLens](./NovaLens.md)
- [APIReference](./APIReference.md)
- [RuntimeAndControlPlane](./RuntimeAndControlPlane.md)
- [NovaSynthPredictiveEngineShifting](./NovaSynthPredictiveEngineShifting.md)
- [NovaAgents](./NovaAgents.md)
- [NovaMesh](./NovaMesh.md)
- [AtheriaContinuousEvolutionAndLiveStream](./AtheriaContinuousEvolutionAndLiveStream.md)
- [AtheriaVoice](./AtheriaVoice.md)
- [AtheriaALSForDevelopers](./AtheriaALSForDevelopers.md)

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
| `DurableControlPlane` | Queue, Schedules, Replay und Status |
| `NovaControlPlaneAPIServer` | HTTP-API fuer die Plattform |
| `PredictiveEngineShifter` | forecast-basierte Engine-Wahl und delegierte Ausfuehrung |

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

## Typische Fehler und Fragen

### Wann ist ein Problem ein Parser- und wann ein Runtime-Problem?

Wenn `ns.graph` funktioniert, aber `ns.run` nicht, ist die Syntax meist korrekt und der Fehler liegt spaeter im Laufzeitpfad.

### Wo fuehrt die Runtime Agenten aus?

Nicht isoliert von allem anderen, sondern im `RuntimeContext` zusammen mit State, Events, Services und Mesh.

### Wo beginnt man bei Plattformfehlern?

Mit `ns.status`, `ns.control` und den API- oder Trace-Pfaden.

## Verwandte Seiten

- [RuntimeMethodReference](./RuntimeMethodReference.md)
- [APIReference](./APIReference.md)
- [RuntimeAndControlPlane](./RuntimeAndControlPlane.md)
- [NovaSynthPredictiveEngineShifting](./NovaSynthPredictiveEngineShifting.md)
- [NovaAgents](./NovaAgents.md)
- [NovaMesh](./NovaMesh.md)

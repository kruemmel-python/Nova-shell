# Nova Runtime

## Zweck

`NovaRuntime` ist die zentrale Laufzeit fuer deklarative `.ns`-Programme.
Sie kompiliert, laedt, fuehrt aus, emittiert Events und stellt Plattformdienste bereit.

## Kernobjekte

- `NovaRuntime`
- `RuntimeContext`
- `CompiledNovaProgram`
- `NovaRuntimeResult`
- `BackendRouter`
- `DurableControlPlane`
- `NovaControlPlaneAPIServer`

## Methoden und Schnittstellen

### Lebenszyklus

```text
compile -> load -> execute_flow / run / emit -> snapshot / resume -> close
```

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

### Eingebaute Toolpfade

- `rss.fetch`
- `atheria.embed`
- `system.log`
- `event.emit`
- `flow.run`
- `state.set`
- `state.get`
- `service.deploy`
- `package.install`

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

## Beispiele

```python
from nova.runtime.runtime import NovaRuntime

source = \"\"\"
agent helper {
  model: local
}

dataset notes {
  items: [{text: "hello"}]
}

flow boot {
  helper summarize notes -> summary
}
\"\"\"

with NovaRuntime() as runtime:
    result = runtime.run(source)
    print(result.context_snapshot)
```

## Verwandte Seiten

- [RuntimeMethodReference](./RuntimeMethodReference.md)
- [APIReference](./APIReference.md)
- [NovaAgents](./NovaAgents.md)
- [NovaMesh](./NovaMesh.md)
- [PageTemplate](./PageTemplate.md)

# Runtime and Control Plane

## Zweck

Diese Seite beschreibt den deklarativen Laufzeitkern von Nova-shell als AI-Operating-System-Runtime.

## Zentrale Quellen

- [docs/NOVA_AI_OS_ARCHITECTURE](../docs/NOVA_AI_OS_ARCHITECTURE.md)
- [nova/runtime/runtime.py](../nova/runtime/runtime.py)
- [nova/runtime/context.py](../nova/runtime/context.py)
- [nova/runtime/control_plane.py](../nova/runtime/control_plane.py)
- [nova/runtime/consensus.py](../nova/runtime/consensus.py)
- [nova/runtime/api.py](../nova/runtime/api.py)

## Kernbereiche

- Flow-Ausfuehrung und Graph-Schliessung
- Event-Bus und Event-gebundene Flows
- Queueing, Scheduling, Retries und Backoff
- Konsens, Replikation, Snapshotting und Control-Plane-API
- Runtime-Kontext mit States, Datasets, Outputs und Systemdiensten

## Relevante Beispiele

- [examples/control_plane_runtime.ns](../examples/control_plane_runtime.ns)
- [examples/replicated_control_plane.ns](../examples/replicated_control_plane.ns)
- [examples/consensus_fabric_cluster.ns](../examples/consensus_fabric_cluster.ns)

## Sinnvolle Anschlussseiten

- [MeshAndDistributedExecution](./MeshAndDistributedExecution.md)
- [SecurityAndTrust](./SecurityAndTrust.md)
- [OperationsAndObservability](./OperationsAndObservability.md)

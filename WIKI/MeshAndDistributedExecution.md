# Mesh and Distributed Execution

## Zweck

Diese Seite beschreibt Worker, Mesh-Registry, Remote-Dispatch und standardisierte Executor-Protokolle.

## Zentrale Quellen

- [nova/mesh](../nova/mesh)
- [nova/runtime/executor_daemon.py](../nova/runtime/executor_daemon.py)
- [nova/runtime/executor_job.py](../nova/runtime/executor_job.py)
- [nova/runtime/executors.py](../nova/runtime/executors.py)
- [examples/distributed_pipeline.ns](../examples/distributed_pipeline.ns)
- [examples/ai_os_cluster.ns](../examples/ai_os_cluster.ns)

## Kernbereiche

- Worker-Registrierung
- capability-basiertes Routing
- standardisierte Executor-Tasks
- isolierte Backend-Daemons
- HTTP-gebundener Remote-Dispatch
- Multi-Node-Control-Plane-Anbindung

## Sinnvolle Anschlussseiten

- [RuntimeAndControlPlane](./RuntimeAndControlPlane.md)
- [SecurityAndTrust](./SecurityAndTrust.md)
- [ServiceFabricAndTrafficPlane](./ServiceFabricAndTrafficPlane.md)

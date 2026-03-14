# Data and Execution Engines

## Zweck

Diese Seite konzentriert sich auf die polyglotten Ausfuehrungs- und Datenpfade von Nova-shell.

## Zentrale Quellen

- [Dokumentation](../Dokumentation.md)
- [Tutorial](../Tutorial.md)
- [README](../README.md)
- [nova/runtime/backends.py](../nova/runtime/backends.py)
- [nova/runtime/executors.py](../nova/runtime/executors.py)

## Engines

- Python
- C++
- GPU
- WASM
- System/Shell
- Datenladepfade
- AI- und Memory-gebundene Backend-Operationen

## Datenpfade

- `data` und `data.load`
- `zero` fuer Zero-Copy
- `fabric` fuer Transfer- und Fabric-Pfade
- persistente States, Outputs und Embeddings im Runtime-Kontext

## Sinnvolle Anschlussseiten

- [CLIAndLegacyRuntime](./CLIAndLegacyRuntime.md)
- [RuntimeAndControlPlane](./RuntimeAndControlPlane.md)
- [OperationsAndObservability](./OperationsAndObservability.md)

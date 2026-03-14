# Nova Language

## Zweck

Diese Seite fasst den deklarativen Sprachpfad von Nova-shell zusammen: `.ns`-Dateien, AST, Graph-Compiler, Imports und die neue Toolchain.

## Zentrale Quellen

- [docs/NOVA_AI_OS_ARCHITECTURE](../docs/NOVA_AI_OS_ARCHITECTURE.md)
- [nova/parser](../nova/parser)
- [nova/graph](../nova/graph)
- [nova/toolchain](../nova/toolchain)
- [examples](../examples)

## Sprachbausteine

- `agent`
- `dataset`
- `flow`
- `state`
- `event`
- `tool`
- `service`
- `package`
- `system`
- `import`

## Toolchain

- Modulauflösung und Lockfiles in [nova/toolchain/loader.py](../nova/toolchain/loader.py)
- Registry in [nova/toolchain/registry.py](../nova/toolchain/registry.py)
- Formatter in [nova/toolchain/formatter.py](../nova/toolchain/formatter.py)
- Linter in [nova/toolchain/linter.py](../nova/toolchain/linter.py)
- LSP-Fassade in [nova/toolchain/lsp.py](../nova/toolchain/lsp.py)
- `.ns`-Test-Runner in [nova/toolchain/testing.py](../nova/toolchain/testing.py)

## Beispiele

- [examples/market_radar.ns](../examples/market_radar.ns)
- [examples/service_package_platform.ns](../examples/service_package_platform.ns)
- [examples/consensus_fabric_cluster.ns](../examples/consensus_fabric_cluster.ns)

## Sinnvolle Anschlussseiten

- [RuntimeAndControlPlane](./RuntimeAndControlPlane.md)
- [AgentsAndKnowledge](./AgentsAndKnowledge.md)
- [ToolchainAndTesting](./ToolchainAndTesting.md)

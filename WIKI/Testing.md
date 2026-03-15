# Testing

## Testebenen

- Parser und AST
- Graph Compiler
- Runtime
- Shell und CLI
- Toolchain
- Service- und Traffic-Plane
- Control Plane und Consensus

## Typische Befehle

```bash
python -m unittest tests.test_nova_language
python -m unittest tests.test_nova_shell
python -m compileall nova nova_shell.py
```

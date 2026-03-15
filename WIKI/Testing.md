# Testing

## Zweck

Diese Seite beschreibt die Testebenen von Nova-shell und zeigt die wichtigsten Testkommandos fuer lokale Entwicklung und Release-Pfade.

## Testebenen

- Parser und AST
- Graph Compiler
- Runtime
- Shell und CLI
- Toolchain
- Service- und Traffic-Plane
- Control Plane und Consensus

## Wichtige Befehle

### Gesamter Testlauf

```powershell
python -m unittest discover -s tests -p "test_*.py"
```

### Fokus auf Sprach- und Runtime-Tests

```powershell
python -m unittest tests.test_nova_language
```

### Fokus auf Shell- und CLI-Tests

```powershell
python -m unittest tests.test_nova_shell
```

### Syntax- und Importpruefung

```powershell
python -m compileall nova nova_shell.py
```

## Wann welcher Test sinnvoll ist

- Parser- oder AST-Aenderungen: `tests.test_nova_language`
- CLI- oder Kommandoaenderungen: `tests.test_nova_shell`
- Build- oder Packaging-Aenderungen: zusaetzlich Release- und Smoke-Pfade pruefen
- Wiki-Aenderungen: `wiki build` als Integrationscheck

## Typische Fehlerbilder

### Einzeltest laeuft, Gesamtsuite nicht

Dann ist oft globaler Zustand, Dateisystemzustand oder eine Seiteneffektkette beteiligt.

### `compileall` scheitert nicht, aber Tests schon

Dann ist die Syntax intakt, aber Semantik oder Integration fehlerhaft.

## Verwandte Seiten

- [DevelopmentGuide](./DevelopmentGuide.md)
- [BuildAndRelease](./BuildAndRelease.md)
- [ToolchainAndTesting](./ToolchainAndTesting.md)

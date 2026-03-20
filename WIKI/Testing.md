# Testing

## Zweck

Diese Seite beschreibt die Testebenen von Nova-shell und zeigt die wichtigsten Testkommandos fuer lokale Entwicklung und Release-Pfade.

## Testebenen

- Parser und AST
- Graph Compiler
- Runtime
- Shell und CLI
- Systemdynamik und Langzeitverhalten
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

### Fokus auf ALS-Systemdynamik

```powershell
python -m unittest tests.test_nova_shell.NovaShellTests.test_atheria_als_learning_changes_output_after_feedback_training
python -m unittest tests.test_nova_shell.NovaShellTests.test_atheria_als_no_extreme_drift_under_stable_signal
python -m unittest tests.test_nova_shell.NovaShellTests.test_atheria_als_focus_stability_under_consistent_signal
python -m unittest tests.test_nova_shell.NovaShellTests.test_atheria_als_memory_influences_future_answers
```

### Syntax- und Importpruefung

```powershell
python -m compileall nova nova_shell.py
```

## Wann welcher Test sinnvoll ist

- Parser- oder AST-Aenderungen: `tests.test_nova_language`
- CLI- oder Kommandoaenderungen: `tests.test_nova_shell`
- ALS-, Memory- oder Resonanzaenderungen: zusaetzlich Systemdynamik-Tests aus `tests.test_nova_shell`
- Build- oder Packaging-Aenderungen: zusaetzlich Release- und Smoke-Pfade pruefen
- Wiki-Aenderungen: `wiki build` als Integrationscheck

## Systemdynamik-Tests

Nova-shell testet Atheria ALS nicht mehr nur als reine Softwareoberflaeche, sondern auch als dynamisches System.

Die aktuelle Suite deckt unter anderem ab:

- Lern-Test: Feedback oder Training veraendert spaetere Antworten
- Drift-Test: Resonanzwerte laufen ueber viele Zyklen nicht unkontrolliert davon
- Stabilitaets-Test: der Fokus bleibt bei stabilem Signal konsistent
- Memory-Test: gespeichertes Wissen beeinflusst spaetere Antworten nachvollziehbar

## Typische Fehlerbilder

### Einzeltest laeuft, Gesamtsuite nicht

Dann ist oft globaler Zustand, Dateisystemzustand oder eine Seiteneffektkette beteiligt.

### `compileall` scheitert nicht, aber Tests schon

Dann ist die Syntax intakt, aber Semantik oder Integration fehlerhaft.

## Verwandte Seiten

- [DevelopmentGuide](./DevelopmentGuide.md)
- [BuildAndRelease](./BuildAndRelease.md)
- [ToolchainAndTesting](./ToolchainAndTesting.md)

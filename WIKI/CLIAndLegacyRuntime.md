# CLI And Legacy Runtime

## Zweck

Die Shell-Runtime in `nova_shell.py` ist der historische Kern des Projekts. Sie existiert parallel zur deklarativen Nova-Runtime und bleibt fuer interaktive Arbeit zentral.

## Kernpunkte

- Die Legacy-Runtime deckt direkte Shellkommandos fuer Compute, AI, Memory, Tools, Mesh und Guard ab.
- Sie ist sofort interaktiv und braucht kein `.ns`-Programm, um zu funktionieren.
- Viele Plattformfunktionen wie `wiki`, `vision`, `mesh start-worker` oder `tool register` sind weiterhin shell-zentriert.
- Die deklarative Runtime baut auf dieser Shell-Umgebung auf, ersetzt sie aber nicht vollstaendig.

## Praktische Nutzung

- Nutze die Shell-Runtime fuer Diagnose, Exploration und Ad-hoc-Operationen.
- Nutze `.ns`-Dateien, sobald du reproduzierbare Flows und Plattformzustand modellieren willst.
- Lerne beide Pfade bewusst getrennt, damit Fehler nicht zwischen Shell- und Declarative-Laufzeit verwechselt werden.

## Testbare Einstiege

### Sofort nutzbare Shellpfade

```powershell
doctor
py 1 + 1
memory status
wiki status
mesh list
```

Erwartung:

- Die Befehle funktionieren ohne `.ns`-Datei.
- Sie pruefen unterschiedliche Teile der klassischen Shell-Runtime.

## Typische Fragen und Fehler

### Wann man den falschen Runtimepfad benutzt

- `ns.graph` und `ns.run` erwarten deklarative Programme.
- Viele Shellkommandos wie `memory`, `tool` oder `guard` brauchen kein `.ns`-Modell.
- Nutze `NovaCLI` und `ProgrammingWithNovaShell` als Entscheidungshilfe.

## Verwandte Seiten

- [NovaCLI](./NovaCLI.md)
- [ProgrammingWithNovaShell](./ProgrammingWithNovaShell.md)
- [NovaRuntime](./NovaRuntime.md)
- [ShellCommandReference](./ShellCommandReference.md)

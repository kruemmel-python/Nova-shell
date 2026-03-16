# Installation

## Zweck

Diese Seite beschreibt die saubere Installation von Nova-shell fuer Entwicklung, lokale Nutzung und Windows-Release-Betrieb.

## Anforderungen

- Python `3.12+`
- Windows oder Linux
- fuer bestimmte Pfade optional: C++-Toolchain, WASM-Tooling, GPU- oder AI-Provider

## Installationsarten

### Installation aus dem Quellbaum

```powershell
git clone <repository-url>
cd Nova-shell-main
python -m pip install -e .
```

Das ist der beste Weg fuer Entwicklung und direkte Arbeit am Repo.

### Direkter Start ohne Paketinstallation

```powershell
python -m nova_shell
```

### Paketinstallation

```powershell
python -m pip install .
nova-shell
```

## Optionale Extras

Das Projekt bietet optionale Feature-Sets fuer:

- Observability
- Guard
- Arrow
- WASM
- GPU
- Atheria
- Release

Je nach Profil sind nicht alle Extras noetig. Welche Faehigkeiten wirklich verfuegbar sind, zeigt `doctor`.

## Windows-MSI und Upgrade

Fuer bestehende Installationen unter `C:\Program Files\Nova-shell` gibt es einen Upgrade-Helper.
Er stoppt laufende `nova_shell.exe`-Prozesse, sichert Runtime-Daten wie `Atheria`, spielt das neue MSI per Reinstall ein und prueft danach `doctor`, `wiki help` und `wiki build`.

Aus dem Repository:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\upgrade_windows_install.ps1
```

Mit explizitem Installer:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\upgrade_windows_install.ps1 -InstallerPath H:\Nova-shell-main\dist\release\windows-amd64\core\installers\nova-shell-0.8.13-windows-x64-core.msi
```

Nur den Ablauf pruefen:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\upgrade_windows_install.ps1 -DryRun
```

## Verifikation

### Minimaler Starttest

```powershell
nova-shell --no-plugins -c "py 1 + 1"
```

### Vollere Diagnose

```powershell
doctor
wiki build
```

### Deklarative Runtime pruefen

```powershell
ns.graph examples\market_radar.ns
```

## Typische Fehler

### `nova-shell` wird nicht gefunden

Dann entweder `python -m nova_shell` verwenden oder die Paketinstallation pruefen.

### `doctor` zeigt fehlende Faehigkeiten

Dann ist oft nur ein optionales Modul nicht vorhanden, nicht die gesamte Installation kaputt.

### Neues Feature wie `wiki` fehlt nach Update

Dann laeuft oft noch eine aeltere installierte Version, nicht der aktuelle Build.

## Verwandte Seiten

- [QuickStart](./QuickStart.md)
- [Troubleshooting](./Troubleshooting.md)
- [BuildAndRelease](./BuildAndRelease.md)
- [NovaCLI](./NovaCLI.md)

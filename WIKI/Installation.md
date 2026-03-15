# Installation

## Anforderungen

- Python `3.12+`
- Windows oder Linux

## Installation aus dem Quellbaum

```bash
git clone <repository-url>
cd Nova-shell-main
python -m pip install -e .
```

## Direkter Start ohne Paketinstallation

```bash
python -m nova_shell
```

## Paketinstallation

```bash
python -m pip install .
```

Danach:

```bash
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

## Windows MSI Upgrade

Fuer eine bestehende Installation unter `C:\Program Files\Nova-shell` gibt es
einen Upgrade-Helper. Er stoppt laufende `nova_shell.exe`-Prozesse, sichert
Runtime-Daten wie `Atheria`, spielt das neue MSI per Reinstall ein und prueft
danach `doctor`, `wiki help` und `wiki build`.

Aus dem Repository:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\upgrade_windows_install.ps1
```

Mit explizitem Installer:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\upgrade_windows_install.ps1 -InstallerPath H:\Nova-shell-main\dist\release\windows-amd64\core\installers\nova-shell-0.8.12-windows-x64-core.msi
```

Nur den Ablauf pruefen:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\upgrade_windows_install.ps1 -DryRun
```

## Verifikation

```bash
nova-shell --no-plugins -c "py 1 + 1"
```

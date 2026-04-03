# Android Preview

Dieser Ordner ist ein erster Android-Pfad fuer Nova-shell. Er ist bewusst getrennt von den bestehenden Windows- und Linux-Releases und nutzt `Chaquopy`, um einen mobilen, Python-basierten Nova-shell-Subset als APK auszuliefern.

## Status

- Ziel: APK fuer einen mobilen, UI-basierten Ein-Kommandopfad statt voller Desktop-REPL.
- Packaging: separates `android/`-Projekt, noch nicht in `scripts/build_release.py` integriert.
- Runtime: generiertes Staging direkt unter `android/app/src/main/python/`, damit die Nova-shell-Runtime ohne externen Schritt in die APK eingebettet wird.

## Aktueller Umfang

Geeignet fuer:

- `doctor`, `help`, `event`, `agent`, `ai`, `memory`
- `ns.run`, `ns.exec`, `ns.graph`, `ns.status`
- lokale `.ns`-Beispiele und repo-nahe Datenfiles
- zusaetzlich jetzt auch Client-/Operator-Pfade wie `remote`, `pulse`, `mesh`, `wiki`, `vision`, `sys`

Hart blockiert bleiben nur lokal schwergewichtige Toolchain- und Hardwarepfade:

- `cpp`, `gpu`, `wasm`, `jit_wasm`

Alle anderen Kommandogruppen werden jetzt an die Runtime durchgereicht. Das heisst: Die App blockiert sie nicht mehr pauschal, aber einzelne Subkommandos koennen auf Android weiterhin mit einer sauberen Capability- oder Host-Fehlermeldung enden.

## Vorbereitung

1. Aus dem Repo-Root das mobile Runtime-Staging erzeugen. Dabei werden `nova_shell.py`, `nova/`, `examples/` und die noetigen Begleitdateien direkt nach `android/app/src/main/python/` kopiert:

```powershell
python scripts\build_android.py prepare
```

2. Danach das Projekt `android/` in Android Studio oeffnen oder Gradle lokal nutzen.

## APK bauen

Debug-APK:

```powershell
python scripts\build_android.py assemble --variant debug
```

Release-APK:

```powershell
python scripts\build_android.py assemble --variant release
```

Wenn kein Gradle im Pfad liegt, das Projekt direkt in Android Studio oeffnen.

## Technische Leitplanken

- Chaquopy `17.0.0`
- Android Gradle Plugin `8.8.2`
- Python `3.12`
- `minSdk 24`
- Ziel-ABIs: `arm64-v8a`, `x86_64`

## Hinweise

- Die Android-App arbeitet absichtlich nicht als vollstaendiger Ersatz fuer die Desktop-Shell.
- Das Staging im Python-Root ist generiert und per `.gitignore` aus dem normalen Repo-Workflow herausgenommen.
- Fuer echte Release-Automation sollte spaeter ein eigener Android-Releasepfad mit Signierung und Artefakt-Upload hinzukommen.

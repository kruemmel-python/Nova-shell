# Build And Release

## Zweck

Diese Seite beschreibt den technischen Weg von Quellstand, Tests und Packaging bis zum veroeffentlichten Artefakt.

## Kernpunkte

- Nova-shell besitzt getrennte Pfade fuer Python-Artefakte, Standalone-Bundle, MSI, Manifest, SBOM und Checksums.
- Der Windows-Releasepfad verwendet `scripts/build_windows.ps1` und `scripts/build_release.py`.
- Fuer reproduzierbare lokale Windows-Builds wird aktuell `D:\NovaShell-release` als Ausgabeziel verwendet.
- Vor einem Release sollten Tests, Compile-Check und mindestens ein Smoke-Test des Bundles gruen sein.
- GitHub-Tag und GitHub-Release werden nach dem Artefaktbau aus dem verifizierten Stand erzeugt.

## Praktische Nutzung

- Nutze `python -m unittest discover -s tests -p "test_*.py"` fuer den kompletten Testlauf.
- Nutze `powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1 -Profile core -SkipTests` fuer den Windows-Core-Build.
- Nutze den direkten `--mode installers`-Pfad, wenn der Bundle-Stand bereits gebaut und verifiziert wurde.
- Nutze `--output-dir D:\NovaShell-release`, damit Build-Artefakte nicht mit dem Quellbaum vermischt werden.

## Testbare Einstiege

### Release lokal vorbereiten

```powershell
python -m unittest discover -s tests -p "test_*.py"
python -m compileall nova nova_shell.py release_packaging.py scripts\build_release.py
python scripts\build_release.py --profile core --mode all --output-dir D:\NovaShell-release
```

Erwartung:

- Tests, Compile-Check und Build laufen ohne Fehler.
- Unter `D:\NovaShell-release\windows-amd64\core` liegen MSI, Wheel, Source-Tarball, Manifest, SBOM und Checksums.

### GitHub Release veroeffentlichen

```powershell
git push origin main
git tag v0.8.26
git push origin v0.8.26
gh release create v0.8.26 --repo kruemmel-python/Nova-shell --title "Nova-shell 0.8.26" --notes-file D:\NovaShell-release\release-notes-v0.8.26.md D:\NovaShell-release\windows-amd64\core\installers\nova-shell-0.8.26-windows-x64-core.msi D:\NovaShell-release\windows-amd64\core\nova-shell-0.8.zip D:\NovaShell-release\windows-amd64\core\python\nova_shell-0.8.26-py3-none-any.whl D:\NovaShell-release\windows-amd64\core\python\nova_shell-0.8.26.tar.gz
```

Erwartung:

- Der Tag existiert remote.
- Der GitHub-Release besitzt die benoetigten Assets.

## Warum ein neues MSI kleiner sein kann

Ein kleineres MSI ist nicht automatisch ein Verlust an Funktion.
Im aktuellen Windows-Core-Pfad wurden zwei Dinge verbessert:

- `pyarrow` wird nicht mehr unnoetig in den Nuitka-Compile-Graph gezogen, sondern sauber einmal als Side-Load bereitgestellt.
- Das MSI filtert Build-Muell wie `.smoke-temp`, `__pycache__`, `.pyc` und `.pyo` konsequent heraus.
- Fuer speicherkritische Windows-Builds nutzt der Releasepfad konservative MSVC-Compile-Flags, damit der Standalone-Build stabil bleibt.

Dadurch wird der Installer kleiner, waehrend Laufzeit und Funktionsumfang gleich bleiben.

## Typische Fragen und Fehler

### MSI-Build bricht auf Windows ab

- WiX oder die Visual-Studio-Build-Umgebung fehlen.
- Der Bundle-Pfad ist noch nicht fertig gestaged.
- Die Release-Logs in `dist/release/logs/` zeigen den letzten erfolgreichen Schritt.

## Verwandte Seiten

- [Testing](./Testing.md)
- [Installation](./Installation.md)
- [Roadmap](./Roadmap.md)
- [Troubleshooting](./Troubleshooting.md)

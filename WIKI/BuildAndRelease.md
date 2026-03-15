# Build And Release

## Zweck

Diese Seite beschreibt den technischen Weg von Quellstand, Tests und Packaging bis zum veroeffentlichten Artefakt.

## Kernpunkte

- Nova-shell besitzt getrennte Pfade fuer Python-Artefakte, Standalone-Bundle, MSI, Manifest, SBOM und Checksums.
- Der Windows-Releasepfad verwendet `scripts/build_windows.ps1` und `scripts/build_release.py`.
- Vor einem Release sollten Tests, Compile-Check und mindestens ein Smoke-Test des Bundles gruen sein.
- GitHub-Tag und GitHub-Release werden nach dem Artefaktbau aus dem verifizierten Stand erzeugt.

## Praktische Nutzung

- Nutze `python -m unittest discover -s tests -p "test_*.py"` fuer den kompletten Testlauf.
- Nutze `powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1 -Profile core -SkipTests` fuer den Windows-Core-Build.
- Nutze den direkten `--mode installers`-Pfad, wenn der Bundle-Stand bereits gebaut und verifiziert wurde.

## Testbare Einstiege

### Release lokal vorbereiten

```powershell
python -m unittest discover -s tests -p "test_*.py"
python -m compileall nova nova_shell.py release_packaging.py scripts\build_release.py
powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1 -Profile core -SkipTests
```

Erwartung:

- Tests, Compile-Check und Build laufen ohne Fehler.
- Unter `dist/release/windows-amd64/core` liegen MSI, Wheel, Source-Tarball, Manifest, SBOM und Checksums.

### GitHub Release veroeffentlichen

```powershell
git push origin main
git tag v0.8.12
git push origin v0.8.12
gh release create v0.8.12 --repo kruemmel-python/Nova-shell --title "Nova-shell 0.8.12" --notes-file H:\Nova-shell-main\dist\release\release-notes-v0.8.12.md H:\Nova-shell-main\dist\release\windows-amd64\core\installers\nova-shell-0.8.12-windows-x64-core.msi
```

Erwartung:

- Der Tag existiert remote.
- Der GitHub-Release besitzt die benoetigten Assets.

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

# Lens Recipes

## Zweck

Diese Seite sammelt direkte Copy-Paste-Rezepte fuer typische Arbeiten mit
`Nova Lens`.

Sie ist absichtlich praktisch aufgebaut:

- wenig Theorie
- konkrete Befehle
- kurze Einordnung

Die Grundlagen stehen in:

- [NovaLens](./NovaLens.md)
- [LensForDevelopers](./LensForDevelopers.md)
- [LensTroubleshooting](./LensTroubleshooting.md)

## Rezept 1: letzten Snapshot sofort ansehen

```powershell
lens last
```

Nutzen:

- schnellster Einstieg in den aktuellen Lens-Zustand
- zeigt den juengsten Snapshot ohne lange Listenansicht

## Rezept 2: die letzten 10 Snapshots anzeigen

```powershell
lens list 10
```

Nutzen:

- Verlauf sehen
- Snapshot-ID fuer weitere Schritte finden

## Rezept 3: einen Snapshot komplett lesen

```powershell
lens show <snapshot_id>
```

Beispiel:

```powershell
lens show 8ba80d6cac4f
```

Nutzen:

- `stage`
- `trace_id`
- `output_hash`
- `data_hash`
- rekonstruierter Output
- rekonstruierte Datenvorschau

## Rezept 4: gespeicherten Output erneut ausgeben

```powershell
lens replay <snapshot_id>
```

Beispiel:

```powershell
lens replay 8ba80d6cac4f
```

Nutzen:

- gespeicherten Output wieder anzeigen
- ohne die eigentliche Stage neu auszufuehren

## Rezept 5: von Snapshot-ID zu CAS-Datei gehen

Schritt 1:

```powershell
lens show <snapshot_id>
```

Schritt 2:
`output_hash` und `data_hash` aus dem Ergebnis nehmen

Schritt 3:

```powershell
Get-Content .\.nova_lens\cas\<output_hash>
Get-Content .\.nova_lens\cas\<data_hash>
```

Nutzen:

- direkte Sicht auf die gespeicherte Payload
- hilfreich fuer Debugging ausserhalb der Lens-CLI

## Rezept 6: CAS-Groessen schnell messen

```powershell
Get-ChildItem .\.nova_lens\cas | Measure-Object -Property Length -Sum -Average
```

Nutzen:

- Gesamtgroesse des CAS
- Durchschnittsgroesse der Eintraege

## Rezept 7: alle CAS-Dateien auflisten

```powershell
Get-ChildItem .\.nova_lens\cas | Select-Object Name,Length,LastWriteTime
```

Nutzen:

- schnelle Sicht auf kleine, leere und grosse Hash-Dateien
- hilfreich fuer visuelle Plausibilitaetspruefung

## Rezept 8: Snapshot-Zahlen direkt aus SQLite holen

```powershell
python - <<'PY'
import sqlite3
from pathlib import Path

db = Path(".nova_lens/lineage.db")
conn = sqlite3.connect(db)
print("snapshots", conn.execute("select count(*) from snapshots").fetchone()[0])
print("forks", conn.execute("select count(*) from forks").fetchone()[0])
conn.close()
PY
```

Nutzen:

- schneller struktureller Check
- unabhaengig von Lens-CLI-Ausgabe

## Rezept 9: alle referenzierten Hashes gegen den CAS pruefen

```powershell
python - <<'PY'
import sqlite3
from pathlib import Path

base = Path(".nova_lens")
conn = sqlite3.connect(base / "lineage.db")
hashes = set()
for row in conn.execute("select output_hash, data_hash from snapshots"):
    hashes.update([x for x in row if x])
for row in conn.execute("select diff_hash, simulation_hash, fork_output_hash, fork_data_hash from forks"):
    hashes.update([x for x in row if x])
cas_files = {p.name for p in (base / "cas").iterdir() if p.is_file()}
print("referenced", len(hashes))
print("cas_files", len(cas_files))
print("missing", sorted(hashes - cas_files)[:10])
print("unreferenced", sorted(cas_files - hashes)[:10])
conn.close()
PY
```

Nutzen:

- fehlende Hash-Dateien finden
- unreferenzierte Restdateien finden

## Rezept 10: nur lesend prüfen, ob ein leerer Hash normal ist

```powershell
Get-Content .\.nova_lens\cas\e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
```

Erwartung:

- keine sichtbare Ausgabe

Das ist normal.
Dieser Hash steht fuer einen leeren Inhalt.

## Rezept 11: den gesamten Lens-Store bewusst zuruecksetzen

```powershell
Remove-Item .\.nova_lens -Recurse -Force
```

Wirkung:

- alle Snapshots weg
- alle Forks weg
- alle CAS-Dateien weg

Nur verwenden, wenn du die Historie wirklich verwerfen willst.

## Rezept 12: einen Watch- oder Guard-Lauf mit Lens zusammendenken

Wenn du mit einem Watcher arbeitest:

```powershell
ns.run nova_project_monitor.ns
```

oder:

```powershell
ns.run nova_system_guard.ns
```

Dann prüfst du parallel:

```powershell
lens last
lens list 5
```

Nutzen:

- Fachreport in `.nova_project_monitor/` oder `.nova_system_guard/`
- Shell-Lineage in `.nova_lens/`

So kannst du HTML-Report und interne Shell-Stufen zusammen nachvollziehen.

## Rezept 13: den aktuellen lokalen Beispielzustand prüfen

Wenn du denselben Typ Zustand wie im aktuellen `C:\NovaShell\monitors`-Lauf
prüfen willst:

```powershell
Get-ChildItem C:\NovaShell\monitors\.nova_lens\cas | Measure-Object
python - <<'PY'
import sqlite3
from pathlib import Path

base = Path(r"C:\NovaShell\monitors\.nova_lens")
conn = sqlite3.connect(base / "lineage.db")
hashes = set()
for row in conn.execute("select output_hash, data_hash from snapshots"):
    hashes.update([x for x in row if x])
for row in conn.execute("select diff_hash, simulation_hash, fork_output_hash, fork_data_hash from forks"):
    hashes.update([x for x in row if x])
cas_files = {p.name for p in (base / "cas").iterdir() if p.is_file()}
print("cas_files", len(cas_files))
print("referenced", len(hashes))
print("unreferenced", len(cas_files - hashes))
conn.close()
PY
```

Nutzen:

- konsistenter Schnellcheck fuer einen echten Arbeitslauf

## Rezept 14: sicher herausfinden, was man nicht loeschen sollte

Nicht selektiv loeschen:

```text
.nova_lens\cas\<einzelne_hash_datei>
.nova_lens\lineage.db
```

wenn der restliche Store erhalten bleiben soll.

Sichere Regel:

- entweder nur lesen
- oder den gesamten `.nova_lens`-Ordner bewusst zuruecksetzen

## Verwandte Seiten

- [NovaLens](./NovaLens.md)
- [LensForDevelopers](./LensForDevelopers.md)
- [LensTroubleshooting](./LensTroubleshooting.md)
- [Troubleshooting](./Troubleshooting.md)

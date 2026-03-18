# Lens Troubleshooting

## Zweck

Diese Seite sammelt typische Stoerungsbilder rund um `Nova Lens` und zeigt, wie
man sie als Entwickler oder Betreiber sauber diagnostiziert.

Im Fokus stehen:

- kaputte oder fehlende CAS-Referenzen
- leere Replays
- unerwartet grosser Lens-Ordner
- Reset und Cleanup
- sichere und unsichere Loeschaktionen

Die Grundlagen stehen in:

- [NovaLens](./NovaLens.md)
- [LensForDevelopers](./LensForDevelopers.md)

## Schnellpruefung

Wenn Lens merkwuerdig wirkt, zuerst:

```powershell
lens last
lens list 10
```

Danach den Zustand auf Platte pruefen:

```powershell
Get-ChildItem .\.nova_lens
Get-ChildItem .\.nova_lens\cas | Measure-Object
```

Wenn du die Datenbank direkt pruefen willst:

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

## Problem: `lens show` findet einen Snapshot, aber Output fehlt

### Symptom

- `lens show <id>` liefert Metadaten
- `output` oder `data_preview` ist leer
- obwohl du eigentlich Inhalt erwartest

### Typische Ursache

Die Datenbankzeile existiert, aber die referenzierte CAS-Datei fehlt oder ist
manuell geloescht worden.

### Pruefung

1. `lens show <id>` ausfuehren
2. `output_hash` und `data_hash` notieren
3. pruefen, ob beide Dateien in `.nova_lens/cas/` existieren

Beispiel:

```powershell
Get-ChildItem .\.nova_lens\cas\<output_hash>
Get-ChildItem .\.nova_lens\cas\<data_hash>
```

### Bewertung

Wenn die Hash-Datei fehlt:

- die Datenbank ist nicht komplett rekonstruierbar
- Replay dieses Snapshots ist dann nur noch teilweise moeglich

## Problem: `lens replay` gibt nichts oder fast nichts aus

### Symptom

- `lens replay <id>` laeuft
- aber der sichtbare Output ist leer oder unerwartet klein

### Typische Ursachen

- die Stage hatte tatsaechlich keinen sichtbaren Output
- die CAS-Datei fuer `output_hash` ist leer
- die Stage hat nur `data_preview`, aber keinen relevanten `output` geschrieben

### Pruefung

```powershell
lens show <id>
```

Wichtige Felder:

- `output_hash`
- `data_hash`
- `output`
- `data_preview`

Bei Lens ist ein leerer Output nicht automatisch ein Fehler.
Einige Stages speichern nur wenig sichtbaren Text, aber trotzdem eine sinnvolle
Datenvorschau.

## Problem: `.nova_lens/cas` enthaelt viele kleine Dateien

### Symptom

Im `cas`-Ordner liegen:

- `0 B`
- `1 B`
- `22 B`
- `41 B`

große und kleine Hash-Dateien gemischt.

### Bewertung

Das ist normal.
Lens speichert auch:

- leere Strings
- Zeilenumbrueche
- kurze Pfadfragmente
- kleine Vorschautexte

Gerade diese kleinen Dateien sind ein Zeichen dafuer, dass das CAS-Modell
dedupliziert arbeitet.

### Kein Fehlerfall

Kleine CAS-Dateien bedeuten nicht:

- Malware
- Dateikorruption
- Build-Artefakt-Muell

Sie sind meist legitime Snapshot-Payloads.

## Problem: `.nova_lens` wird unerwartet gross

### Symptom

`.nova_lens/` waechst deutlich an, besonders bei:

- langen Watch-Monitor- oder Guard-Laeufen
- grossen eingebetteten `.ns`-Stages
- vielen Shell-Kommandos mit grossen Outputs

### Ursachen

- viele unterschiedliche Outputs
- grosse Text- oder JSON-Outputs
- wenige Wiederholungen, also wenig Deduplikationseffekt

### Was du tun kannst

1. erst messen:

```powershell
Get-ChildItem .\.nova_lens\cas | Measure-Object -Property Length -Sum
```

2. dann pruefen, ob der Store wirklich gebraucht wird
3. nur dann bereinigen, wenn alte Snapshots nicht mehr benoetigt werden

## Problem: Ich will Lens zuruecksetzen

### Sicherer kompletter Reset

Wenn du die Lens-Historie dieses Arbeitsverzeichnisses wirklich komplett
verwerfen willst:

```powershell
Remove-Item .\.nova_lens -Recurse -Force
```

Beim naechsten Lauf wird der Store neu aufgebaut.

### Wirkung

Das entfernt:

- alle Snapshots
- alle Forks
- alle CAS-Dateien
- jede Replay-Basis

Deshalb ist das ein echter Reset, kein harmloser Cleanup.

## Problem: Ich will nur "Muellspeicher" bereinigen

### Wichtig

Nicht blind einzelne Dateien in `.nova_lens/cas` loeschen.

Warum:

- `lineage.db` referenziert diese Hash-Dateien direkt
- geloeschte CAS-Dateien fuehren spaeter zu leeren `output`- oder `data_preview`-Feldern

### Sichere Regel

- entweder den Store ganz behalten
- oder den Store ganz loeschen

Selektives manuelles Loeschen einzelner CAS-Dateien ist fuer normale
Entwicklerablaeufe nicht empfehlenswert.

## Problem: Ich sehe `.nova_lens`, wollte aber nur den System Guard

### Erklaerung

`System Guard` und `Nova Lens` sind zwei verschiedene Persistenzpfade:

- `.nova_system_guard/` -> Fachartefakte des Guards
- `.nova_lens/` -> allgemeine Shell-Lineage

Der Guard kann also:

- seine HTML- und JSON-Berichte schreiben
- und parallel Shell-Snapshots nach Lens ausloesen

Das ist beabsichtigt.

## Problem: Warum fehlt `.nova_lens` im Release-Bundle?

### Erklaerung

`.nova_lens` ist Laufzeitstatus, kein statischer Programmteil.
Deshalb wird er in Release-Bundles nicht als persistente Anwendungsnutzlast
mitgeliefert, sondern bei Bedarf auf dem Zielsystem neu erzeugt.

Fuer Entwickler heisst das:

- im Arbeitsverzeichnis ist `.nova_lens` normal
- im gebauten Release-Bundle sollte er nicht als alter Runtime-Zustand
  mitgeschleppt werden

## Problem: Wie prüfe ich Konsistenz zwischen DB und CAS?

### Praktischer Check

1. alle Hashes aus `lineage.db` sammeln
2. alle Dateinamen in `cas/` sammeln
3. Differenzen betrachten

Wenn du nur schnell einen Zustand beurteilen willst:

- fehlende Hash-Dateien -> problematisch
- unreferenzierte CAS-Dateien -> meist Cleanup-/Historienrest

Im aktuellen lokalen Beispiel unter `C:\NovaShell\monitors\.nova_lens` war der
Zustand sauber:

- `33` CAS-Dateien
- `33` referenzierte Hashes
- `0` unreferenzierte Dateien

## Was du gefahrlos loeschen kannst

### Sicher loeschbar, wenn du Historie bewusst verwerfen willst

- der gesamte Ordner `.nova_lens/`

### Nicht selektiv loeschen

- einzelne Dateien unter `.nova_lens/cas/`
- nur `lineage.db` ohne `cas/`
- nur `cas/` ohne `lineage.db`

### Warum nicht?

Weil du sonst inkonsistente Halbzustände erzeugst:

- DB ohne Payload
- Payload ohne Index
- Snapshots ohne Replay-Basis

## Empfohlene Diagnose-Reihenfolge

1. `lens last`
2. `lens show <id>`
3. `.nova_lens/lineage.db` vorhanden?
4. `.nova_lens/cas/` vorhanden?
5. referenzierte Hash-Datei vorhanden?
6. erst danach Reset oder Cleanup

## Verwandte Seiten

- [NovaLens](./NovaLens.md)
- [LensForDevelopers](./LensForDevelopers.md)
- [LensRecipes](./LensRecipes.md)
- [Troubleshooting](./Troubleshooting.md)
- [OperationsAndObservability](./OperationsAndObservability.md)
- [SystemGuardMonitor](./SystemGuardMonitor.md)

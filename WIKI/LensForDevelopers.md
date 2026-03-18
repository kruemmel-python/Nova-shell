# Lens For Developers

## Zweck

Diese Seite ist der Low-Level-Guide fuer Entwickler, die `Nova Lens` nicht nur
benutzen, sondern debuggen, erweitern oder betrieblich einordnen wollen.

Im Fokus stehen:

- SQLite-Schema
- Content-Addressable Store
- Snapshot-Lookup
- Replay und Forks
- typische Debug-Rezepte

Die konzeptionelle Einfuehrung steht in [NovaLens](./NovaLens.md).
Diese Seite geht absichtlich eine Ebene tiefer.

Fuer die philosophische und systemische Einordnung von Lens siehe in
[NovaLens](./NovaLens.md) das Kapitel `Optics of Sovereignty`.

## Kernobjekte

| Objekt | Rolle |
| --- | --- |
| `NovaLensStore` | zentraler Store fuer Snapshots und Forks |
| `lineage.db` | Metadaten-Index |
| `cas/` | eigentliche, per Hash benannte Payload-Dateien |
| `snapshots` | Tabelle fuer normale Shell-Stages |
| `forks` | Tabelle fuer hypothetische Varianten |

## Speicherlayout

```text
.nova_lens/
  lineage.db
  cas/
    <sha256>
    <sha256>
    <sha256>
```

### Trennung von Metadaten und Payload

Lens trennt sehr bewusst:

- Metadaten in SQLite
- Nutzinhalte als einzelne Dateien im CAS

Das vermeidet zwei typische Probleme:

1. unstrukturierte Text- oder JSON-Dumps in der Datenbank
2. redundante Mehrfachspeicherung identischer Inhalte

## SQLite-Schema

Der Store initialisiert zwei Haupttabellen:

### `snapshots`

Felder:

- `id`
- `ts`
- `trace_id`
- `stage`
- `error`
- `data_type`
- `output_hash`
- `data_hash`

Bedeutung:

- `id`: kurze Snapshot-ID fuer CLI und Replay
- `ts`: Zeitstempel
- `trace_id`: Ablauf- oder Trace-Kontext
- `stage`: Shell- oder Pipeline-Stufe
- `error`: eventueller Fehlertext
- `data_type`: Typisierung des Ergebnisses
- `output_hash`: Hash des sichtbaren Outputs
- `data_hash`: Hash der `data_preview`

### `forks`

Felder:

- `id`
- `snapshot_id`
- `ts`
- `namespace`
- `project`
- `inject_json`
- `diff_hash`
- `simulation_hash`
- `fork_output_hash`
- `fork_data_hash`

Bedeutung:

- `snapshot_id`: Referenz auf den Ursprungssnapshot
- `inject_json`: hypothetische Eingabe fuer den Fork
- `diff_hash`: serialisierter Diff im CAS
- `simulation_hash`: Simulationsdaten im CAS
- `fork_output_hash`: hypothetischer Output im CAS
- `fork_data_hash`: hypothetische Datenvorschau im CAS

## CAS-Prinzip

Jede CAS-Datei ist direkt ueber ihren Inhalt adressiert:

```text
dateiname = sha256(payload)
```

Wenn zwei Snapshots denselben Output haben:

- gibt es nur eine CAS-Datei
- beide Datenbankzeilen verweisen auf denselben Hash

Das ist der Kern der Effizienz.

### Typische Sonderfaelle

| Inhalt | Erwarteter Effekt |
| --- | --- |
| leerer String | eine einzelne leere CAS-Datei |
| nur `\n` | eine einzelne 1-Byte-Datei |
| identischer Pfadtext | mehrfach referenziert, aber nur einmal gespeichert |
| grosser Stage-Output | eigene CAS-Datei, nur wenn Inhalt neu ist |

## Lookup-Ablauf

Ein `lens show <id>` ist logisch:

```text
snapshot_id
  ->
lineage.db / snapshots
  ->
output_hash + data_hash
  ->
cas/<output_hash> + cas/<data_hash>
  ->
rekonstruierter Snapshot
```

Das ist wichtig:
Die CLI arbeitet nicht direkt auf Dateinamen, sondern auf Snapshot-IDs.
Die Hash-Dateien sind nur das Payload-Backend.

## Beispiel: aktueller Lauf unter `C:\NovaShell\monitors`

Im aktuellen lokalen Zustand war:

- `.nova_lens/lineage.db` vorhanden
- `.nova_lens/cas/` vorhanden
- `33` CAS-Dateien vorhanden
- alle `33` CAS-Dateien referenziert
- `0` unreferenzierte CAS-Dateien
- `0` Fork-Eintraege

Das ist ein sauberer Zustand.

### Was die kleinen Dateien praktisch bedeuten

Beispiele aus dem aktuellen Lauf:

- `e3b0c442...` -> leerer String
- `01ba4719...` -> nur Zeilenumbruch
- `9dbfc775...` -> `C:\NovaShell\monitors\n`
- `d9431da0...` -> `C:\NovaShell\monitors\.nova_system_guard\n`

Das ist nicht "Muell", sondern absichtlich deduplizierter Snapshot-Inhalt.

### Was die grossen Dateien praktisch bedeuten

Mehrere CAS-Dateien mit etwa `17 KB` bis `24 KB` stammen aus laengeren
Shell-Stages des System-Guard-Laufs, insbesondere aus grossen eingebetteten
Text-Outputs im `.ns`-Pfad.

Das zeigt:

- Lens speichert nicht nur Statusbruchstuecke
- auch grosse Stage-Outputs werden persistiert
- trotzdem bleibt das Modell konsistent, weil alles ueber Hashes referenziert wird

## Debug-Rezepte

### 1. Letzte Snapshots ansehen

```powershell
lens list 10
lens last
```

Nutzen:

- Snapshot-ID finden
- Stage-Verlauf schnell ueberblicken

### 2. Einen Snapshot vollstaendig lesen

```powershell
lens show <snapshot_id>
```

Nutzen:

- `output_hash` sehen
- `data_hash` sehen
- rekonstruierten Output lesen

### 3. Snapshot-Output erneut ausgeben

```powershell
lens replay <snapshot_id>
```

Nutzen:

- gespeicherten Output erneut ausgeben
- ohne die Stage neu auszufuehren

### 4. Datenbank direkt pruefen

PowerShell:

```powershell
python - <<'PY'
import sqlite3
from pathlib import Path

db = Path(r"C:\NovaShell\monitors\.nova_lens\lineage.db")
conn = sqlite3.connect(db)
for row in conn.execute("select id, stage, output_hash, data_hash from snapshots order by ts desc limit 5"):
    print(row)
conn.close()
PY
```

Nutzen:

- direkte Sicht auf den Index
- hilfreich bei Debugging ausserhalb der CLI

### 5. Einen Hash manuell nachschlagen

Wenn du `output_hash` oder `data_hash` kennst:

```powershell
Get-Content C:\NovaShell\monitors\.nova_lens\cas\<hash>
```

Nutzen:

- Payload direkt lesen
- schnelle Verifikation von CAS-Inhalten

## Typische Entwicklerfragen

### Warum speichert Lens Output und `data_preview` getrennt?

Weil sichtbarer Text und strukturierte oder reduzierte Datenvorschau nicht
immer identisch sind.
Die Trennung macht Replay und Analyse klarer.

### Warum nicht alles nur in SQLite speichern?

Weil grosse oder viele wiederholte Inhalte dort ineffizienter und unhandlicher
waeren.
Das CAS-Modell ist fuer Deduplikation deutlich besser geeignet.

### Kann `cas/` unreferenzierte Dateien enthalten?

Ja, theoretisch nach manuellen Eingriffen oder zukuenftigen
Migrationsszenarien.
Im aktuellen Lauf war das aber nicht der Fall: `0` unreferenzierte Dateien.

### Ist Lens Teil der deklarativen Runtime?

Nicht direkt.
Lens sitzt im klassischen Shell-Pfad und wird von dort automatisch beschrieben.
Fuer die Gesamtarchitektur ist es trotzdem ein relevanter Persistenzbaustein.

## Wann Entwickler Lens bewusst brauchen

- bei Debugging von Watchern und Guards
- bei Shell- und Pipeline-Regressionen
- wenn Outputs spaeter reproduzierbar sein muessen
- fuer hypothetische Forks und Diff-Simulationen
- um zu verstehen, warum `.nova_lens/cas` viele Hash-Dateien enthaelt

## Verwandte Seiten

- [NovaLens](./NovaLens.md)
- [LensTroubleshooting](./LensTroubleshooting.md)
- [LensRecipes](./LensRecipes.md)
- [NovaCLI](./NovaCLI.md)
- [ShellCommandReference](./ShellCommandReference.md)
- [NovaRuntime](./NovaRuntime.md)
- [SystemGuardMonitor](./SystemGuardMonitor.md)
- [CodeReferenceIndex](./CodeReferenceIndex.md)

# Nova Lens

## Zweck

`Nova Lens` ist die persistente Verlaufs- und Snapshot-Schicht der klassischen
Nova-shell-Runtime.

Sie speichert nicht einfach nur "Logs", sondern legt nach jeder wichtigen
Shell-Stage nachvollziehbare Snapshots ab:

- welche Stage gelaufen ist
- welcher Output entstanden ist
- welche Datenvorschau zur Stage gehoerte
- welcher Trace-Kontext aktiv war

Das ist fuer Entwickler wichtig, weil damit Shell-, Monitor- und
Automationslaeufe spaeter reproduzierbar, inspizierbar und effizient speicherbar
werden.

## Kernobjekte

| Objekt | Rolle |
| --- | --- |
| `NovaLensStore` | persistenter Lens-Store |
| `.nova_lens/lineage.db` | SQLite-Index fuer Snapshots und Forks |
| `.nova_lens/cas/` | Content-Addressable Store fuer die eigentlichen Inhalte |
| `lens list`, `lens show`, `lens replay` | CLI zum Lesen der gespeicherten Snapshots |
| `lens fork`, `lens diff` | hypothetische Abzweigungen und Diffs ueber Snapshots |

## Wie Lens arbeitet

Das Speichermodell ist zweistufig:

1. Metadaten landen in `lineage.db`
2. eigentliche Inhalte landen in `.nova_lens/cas`

`cas` steht fuer `content-addressable store`.
Das bedeutet:

- der Dateiname ist nicht "report.txt" oder "output-17.json"
- der Dateiname ist der `sha256`-Hash des Inhalts
- identischer Inhalt wird nur einmal gespeichert

Das ist deutlich effizienter als jede Stage separat in eigene Output-Dateien zu
duplizieren.

## Struktur auf der Festplatte

Ein typischer Lens-Ordner sieht so aus:

```text
.nova_lens/
  lineage.db
  cas/
    e3b0c44298fc...
    01ba4719c80b...
    95e9064a54dc...
```

### `lineage.db`

Die Datenbank ist der Index.
Sie speichert unter anderem:

- Snapshot-ID
- Zeitstempel
- Stage-Name
- Trace-ID
- Hash des Outputs
- Hash der Datenvorschau

Die eigentlichen Inhalte selbst liegen nicht direkt in der Tabelle, sondern
werden ueber ihre Hashes auf Dateien in `cas/` referenziert.

### `cas/`

Hier liegen die echten Payloads.
Jede Datei repraesentiert genau einen Inhalt.
Wenn zwei Snapshots denselben Output oder dieselbe Vorschau haben, zeigen beide
nur auf dieselbe CAS-Datei.

## Warum das effizient ist

Die Effizienz entsteht durch Deduplikation.

Beispiele:

- ein leerer String wird nicht 50-mal gespeichert, sondern nur einmal
- ein einzelner Zeilenumbruch wird nicht immer neu geschrieben
- gleiche Pfad- oder Statusfragmente werden wiederverwendet
- groessere Stage-Outputs werden nur dann neu geschrieben, wenn sich ihr Inhalt
  wirklich unterscheidet

Praktisch bedeutet das:

- `lineage.db` bleibt ein kompakter Index
- `cas/` speichert nur einzigartige Inhalte
- Replay und Debugging bleiben moeglich
- wiederholte Monitor- oder Shell-Laufe erzeugen weniger redundante Dateien

## Echtes Beispiel aus dem aktuellen Lauf

Am aktuellen lokalen Lauf in:

```text
C:\NovaShell\monitors\.nova_lens
```

zeigt sich das sehr gut.

In diesem Beispielstand gab es:

- `33` CAS-Dateien
- `33` davon waren von `lineage.db` referenziert
- `0` unreferenzierte CAS-Dateien
- `0` Lens-Forks

Das ist wichtig:
Der Store ist in diesem Lauf vollstaendig konsistent.
Es liegen keine losen Altdateien im CAS-Ordner herum.

### Konkrete CAS-Dateien aus diesem Lauf

| Hash-Datei | Groesse | Inhalt | Bedeutung |
| --- | --- | --- | --- |
| `e3b0c44298fc...` | `0 B` | leerer String | deduplizierte leere Vorschau |
| `01ba4719c80b...` | `1 B` | `"\n"` | deduplizierter einzelner Zeilenumbruch |
| `9dbfc775adc4...` | `22 B` | `C:\NovaShell\monitors\n` | kurze Datenvorschau mit Root-Pfad |
| `d9431da0f26c...` | `41 B` | `C:\NovaShell\monitors\.nova_system_guard\n` | kurze Datenvorschau auf den Guard-State-Pfad |

Diese kleinen Dateien sind kein Fehler.
Sie zeigen gerade den Vorteil des CAS-Modells:

- ein leerer Inhalt bekommt einen stabilen Hash
- ein einfacher Zeilenumbruch bekommt einen stabilen Hash
- dieselben Mini-Payloads werden nicht dupliziert

### Warum einige CAS-Dateien deutlich groesser sind

Im selben Lauf gab es auch CAS-Dateien mit etwa `17 KB` bis `24 KB`.
Diese stammen im aktuellen Monitor-Lauf von laengeren Stage-Outputs, unter
anderem aus dem selbstbootstrappenden `nova_system_guard.ns`-Pfad.

Das bedeutet:

- Lens speichert nicht nur Mini-Vorschauen
- es kann auch groessere Text-Outputs sichern
- trotzdem bleibt die Speicherung effizient, weil identischer Inhalt ueber den
  Hash wiederverwendet wird

## Beziehung zum System Guard

Beim `System Guard` musst du zwei getrennte Persistenzpfade unterscheiden:

- `.nova_system_guard/`
- `.nova_lens/`

### `.nova_system_guard/`

Das ist der Guard-spezifische Betriebszustand:

- HTML-Report
- JSON-Status
- History
- Quarantaene
- Detailseiten

### `.nova_lens/`

Das ist die allgemeine Shell-Lineage:

- Stage-Snapshots
- Output- und Preview-Blobs
- Replay und Fork-Basis

Kurz:
Der Guard schreibt seine Fachartefakte nach `.nova_system_guard`.
Lens speichert parallel die allgemeine Shell-Verlaufsspur.

## CLI fuer Entwickler

### Letzte Snapshots ansehen

```powershell
lens list 8
lens last
```

### Einen Snapshot im Detail laden

```powershell
lens show <snapshot_id>
```

Erwartung:

- Stage-Name
- Zeitstempel
- Trace-ID
- `output_hash`
- `data_hash`
- rekonstruierter `output`
- rekonstruierte `data_preview`

### Snapshot erneut ausgeben

```powershell
lens replay <snapshot_id>
```

Das ist kein "Neuberechnen" der Stage, sondern ein Replay des gespeicherten
Snapshot-Outputs.

### Forks und Diff

```powershell
lens fork <snapshot_id> --inject "{\"severity\": \"high\"}"
lens forks 10
lens diff <fork_id>
```

Damit koennen Entwickler hypothetische Varianten eines Snapshots aufspannen,
ohne den Originalzustand zu ueberschreiben.

## Warum das fuer Entwickler relevant ist

`Nova Lens` ist mehr als eine Komfortfunktion.
Es ist die Bruecke zwischen:

- operativer Shell-Nutzung
- reproduzierbaren Entwicklungsablaeufen
- effizienter Speicherung
- spaeterer Analyse

Gerade fuer Watcher, Guards und laengere Automationspfade ist das wichtig,
weil man nicht nur den letzten HTML-Report sehen will, sondern auch die
einzelnen Shell-Stufen nachvollziehen koennen muss.

## Optics of Sovereignty

Dieses Kapitel beschreibt die tiefere Bedeutung von Lens fuer kuenftige
Experten, Plattformarchitekten und Betreiber.

`Sovereignty` meint hier nicht nur "lokal speichern", sondern die Faehigkeit,
Systemverhalten aus eigener Infrastruktur, eigener Laufzeit und eigenen
Beweisspuren heraus zu verstehen.

`Optics` meint die Art und Weise, wie dieses Verstehen sichtbar gemacht wird.
Lens ist deshalb keine reine Speicheroptimierung, sondern ein Sichtsystem fuer
operative Wahrheit.

### 1. Sichtbarkeit statt Black Box

Viele moderne Runtime- und Agentensysteme liefern am Ende nur:

- den letzten Output
- einen Status `ok` oder `failed`
- vielleicht noch einen Log-Block

Lens geht einen anderen Weg:

- jede relevante Stage kann als Snapshot eingefroren werden
- Outputs und Datenvorschauen bleiben referenzierbar
- die Shell-Lineage wird replaybar

Dadurch entsteht kein blinder Automationsraum, sondern ein System, dessen
Zustaende spaeter wieder eingesehen, verglichen und erklaert werden koennen.

### 2. Eigentum an der Kausalspur

Souveraen ist ein System dann, wenn es seine eigenen Ursachenketten nicht an
fremde Plattformen oder unsichtbare Telemetriesysteme auslagern muss.

Lens schafft dieses Eigentum an der Kausalspur durch:

- lokale Persistenz in `.nova_lens`
- nachvollziehbare Snapshot-IDs
- inhaltsadressierte Payloads in `cas/`
- direkte Rekonstruktion ueber `lineage.db`

Das ist technisch relevant, weil Beweisspur und Nutzsystem dicht beieinander
liegen.
Es ist philosophisch relevant, weil das System nicht nur handelt, sondern seine
eigenen Handlungsreste lesbar konserviert.

### 3. Effizienz als Form von Autonomie

Die content-addressable Speicherung ist nicht nur platzsparend.
Sie ist auch ein Autonomiemechanismus.

Warum:

- identische Inhalte werden nicht immer neu erzeugt
- kleine und grosse Payloads koennen gleichfoermig behandelt werden
- Replay benoetigt keine zweite Speicherlogik
- Monitor- und Shell-Laufe koennen wachsen, ohne sofort in redundanten Dumps zu
  enden

Damit ist Effizienz hier nicht nur ein Performancewert, sondern ein Mittel, um
Komplexitaet unter eigener Kontrolle zu halten.

### 4. Lens als epistemische Infrastruktur

Fuer Experten wird Lens besonders dann wichtig, wenn Nova-shell nicht nur als
Befehlswerkzeug, sondern als Plattform gelesen wird.

In diesem Sinn ist Lens eine epistemische Infrastruktur:

- es speichert nicht einfach Daten
- es speichert lesbare Entscheidungs- und Wirkungsspuren
- es macht spaetere Interpretation moeglich

Gerade bei:

- Watch Monitor
- System Guard
- Blob-Seeds
- Predictive Shifting
- Agenten- und Atheria-nahen Betriebslaeufen

wird Lens damit zu einer Schicht, die technische Operation und Erkenntnis
verbindet.

### 5. Warum das fuer Zukunftssysteme wichtig ist

Je autonomer ein System wird, desto wichtiger wird nicht nur seine Faehigkeit,
etwas zu tun, sondern seine Faehigkeit, spaeter nachvollziehbar zu machen, was
es getan hat.

Die Zukunftsfrage lautet deshalb nicht nur:

> Kann das System handeln?

sondern auch:

> Kann das System seine eigene Handlungsgeschichte in einer kompakten,
> verifizierbaren und lokal kontrollierten Form bewahren?

Lens ist ein Teil dieser Antwort.

### 6. Praktische Lesart fuer Experten

Fuer fortgeschrittene Entwickler bedeutet `Optics of Sovereignty` konkret:

- Logs allein reichen nicht
- Outputs ohne Lineage reichen nicht
- Persistenz ohne Deduplikation wird teuer und unklar
- lokale Autonomie ohne lesbare Kausalspur bleibt technisch schwach

Lens verbindet diese Punkte zu einem Modell, in dem:

- Speicher effizient bleibt
- Snapshots adressierbar bleiben
- Replays moeglich bleiben
- Systemverhalten unter eigener Kontrolle lesbar bleibt

Das ist der eigentliche Mehrwert hinter dem unscheinbaren Ordner
`.nova_lens/cas`.

## Typische Missverstaendnisse

### Sind die Hash-Dateien in `cas/` Malware oder Fremddateien?

Nein.
Das sind interne Nova-shell-Payloads.
Der Dateiname ist der Hash des Inhalts.

### Warum gibt es dort leere oder winzige Dateien?

Weil auch leere oder sehr kleine Inhalte legitime Snapshot-Bloecke sind und
dedupliziert gespeichert werden.

### Warum steht in `cas/` kein sprechender Dateiname?

Weil nicht der Name, sondern der Inhalt die Identitaet bildet.
Das ist der Kern eines content-addressable stores.

### Wird dadurch Speicher verschwendet?

Im Gegenteil.
Genau dadurch wird redundante Speicherung reduziert.

## Verwandte Seiten

- [LensForDevelopers](./LensForDevelopers.md)
- [LensTroubleshooting](./LensTroubleshooting.md)
- [LensRecipes](./LensRecipes.md)
- [NovaCLI](./NovaCLI.md)
- [ShellCommandReference](./ShellCommandReference.md)
- [NovaRuntime](./NovaRuntime.md)
- [SystemGuardMonitor](./SystemGuardMonitor.md)
- [OperationsAndObservability](./OperationsAndObservability.md)
- [CodeReferenceIndex](./CodeReferenceIndex.md)

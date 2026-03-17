# NS Blob Generator

## Zweck

Der NS Blob Generator kapselt Nova-shell-Logik und Daten in ein kompaktes, verifizierbares Seed-Format.
Er ist kein bloßer Kompressor, sondern ein Transport- und Rehydrierungspfad fuer:

- mobile `.ns`-Programme
- eingebettete Python-Logik
- kompakte Text- oder Binaerartefakte
- verifizierbare Mesh-Transfers

Das Format ist auf drei konkrete Vorteile ausgelegt:

- geringere Transport- und Speicherlast
- Integritaetspruefung vor der Ausfuehrung
- direkte Wiederverwendung in CLI, Mesh und deklarativer Runtime

## Kernobjekte

| Objekt | Rolle |
| --- | --- |
| `NovaBlobGenerator` | erzeugt, schreibt, laedt, verifiziert und rehydriert Seeds |
| `NovaBlobSeed` | normierte Seed-Struktur mit Hashes, Metadaten und Payload |
| `INLINE_BLOB_PREFIX` | Prefix `nsblob:` fuer inline transportierbare Seeds |
| `blob` | Shell-Kommando fuer Pack, Verify, Unpack, Exec und Mesh-Run |

## Architektur

```text
source file or inline text
  ->
zlib compression
  ->
base64url encoding
  ->
NovaBlobSeed
  ->
verify / unpack / exec / mesh-run
```

## Integritaet

Jeder Seed traegt:

- `sha256` des Originalinhalts
- `compressed_sha256` des komprimierten Payloads
- Groessen- und Metadaten

Nova-shell kann damit vor jeder Rehydrierung pruefen, ob ein Seed veraendert oder beschaedigt wurde.

## CLI

### Datei in Seed umwandeln

```powershell
blob pack .\workflow.ns --output .\workflow.nsblob.json
```

### Inline-Seed erzeugen

```powershell
blob inline .\workflow.nsblob.json
```

### Seed pruefen

```powershell
blob verify .\workflow.nsblob.json
```

### Seed lokal ausfuehren

```powershell
blob exec .\workflow.nsblob.json
```

### Seed auf einen Worker schicken

```powershell
blob mesh-run cpu .\workflow.nsblob.json
```

## Deklarative Runtime

Die Blob-Schicht ist auch direkt in der deklarativen Runtime verfuegbar:

- `blob.verify`
- `blob.unpack`
- `blob.exec`

Beispiel:

```ns
flow inspect_blob {
  blob.verify "C:/project/workflow.nsblob.json" -> verified
  blob.unpack "C:/project/workflow.nsblob.json" -> unpacked
}

flow execute_blob {
  blob.exec "C:/project/workflow.nsblob.json" -> executed
}
```

## Testbare Beispiele

### 1. Python-Expression als Seed

```powershell
blob pack --text "21 * 2" --type py
```

Danach:

```powershell
blob exec-inline nsblob:...
```

Erwartung:

- Ausgabe `42`

### 2. `.ns`-Programm als Seed

```powershell
blob pack .\workflow.ns --type ns --output .\workflow.nsblob.json
blob verify .\workflow.nsblob.json
blob exec .\workflow.nsblob.json
```

### 3. Seed ueber Mesh transportieren

```powershell
mesh start-worker --caps cpu,py
blob mesh-run cpu .\workflow.nsblob.json
```

## Designentscheidungen

### Warum zlib und base64url?

`zlib` bringt eine einfache, verlustfreie Dichteoptimierung.
`base64url` macht den komprimierten Inhalt texttauglich fuer JSON, inline Strings und transportfreundliche Shell-Pfade.

### Warum kein blinder Binary Dump?

Weil Nova-shell den Seed sowohl lokal in Dateien als auch inline in Kommandos, JSON-Payloads und Mesh-Requests transportieren koennen soll.

### Warum Seeds statt nur `pack`-Archive?

`pack` erzeugt groessere Bundle-Artefakte fuer Distribution.
Blob-Seeds sind dagegen kleine, schnell bewegliche Logik- und Transportkapseln fuer laufende Systeme.

## Typische Fehler und Fragen

### Warum scheitert `blob.exec`?

Typische Gruende:

- Hash-Pruefung fehlgeschlagen
- Blob-Typ nicht ausfuehrbar
- `ns`-Blob ist kein deklarativer Nova-Quelltext

### Wann ist `blob mesh-run` sinnvoll?

Wenn Logik schnell auf einen Worker verschoben werden soll, ohne vorher Dateien, Verzeichnisstrukturen oder Installationen zu synchronisieren.

### Wo liegen Seeds standardmaessig?

Unter Atherias/Nova-shells Storage-Root in:

- `ns_blobs`

## Verwandte Seiten

- [NovaRuntime](./NovaRuntime.md)
- [NovaMesh](./NovaMesh.md)
- [ProgrammingWithNovaShell](./ProgrammingWithNovaShell.md)
- [ExamplesAndRecipes](./ExamplesAndRecipes.md)

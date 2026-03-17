# Tutorial Blob Seeds

## Ziel

Dieses Tutorial zeigt, wie Nova-shell-Logik als Seed gekapselt, verifiziert, lokal ausgefuehrt und ueber Mesh verschoben wird.

Am Ende hast du:

- einen `.ns`-Seed
- einen Python-Seed
- einen lokalen oder entfernten Ausfuehrungspfad
- einen deklarativen Flow, der einen Seed direkt benutzt

## Schritt 1: Einfachen Python-Seed bauen

```powershell
blob pack --text "21 * 2" --type py
```

Die Ausgabe enthaelt:

- `path`
- `inline_seed`
- `sha256`
- `compressed_sha256`

## Schritt 2: Seed verifizieren

```powershell
blob verify .\calc.nsblob.json
```

Erwartung:

- `verified: true`

## Schritt 3: Seed lokal ausfuehren

```powershell
blob exec .\calc.nsblob.json
```

## Schritt 4: `.ns`-Datei als Seed kapseln

Lege zuerst eine kleine Datei an:

```powershell
@'
flow hello {
  system.log "hello from blob" -> out
}
'@ | Set-Content .\hello_blob.ns
```

Dann:

```powershell
blob pack .\hello_blob.ns --type ns --output .\hello_blob.nsblob.json
blob exec .\hello_blob.nsblob.json
```

## Schritt 5: Seed direkt in `.ns` nutzen

```powershell
@'
flow inspect_blob {
  blob.verify ".\\hello_blob.nsblob.json" -> verified
  blob.unpack ".\\hello_blob.nsblob.json" -> unpacked
}
'@ | Set-Content .\blob_runtime.ns

ns.graph .\blob_runtime.ns
ns.run .\blob_runtime.ns
```

## Schritt 6: Seed ueber Mesh laufen lassen

```powershell
mesh start-worker --caps cpu,py
blob mesh-run cpu .\hello_blob.nsblob.json
```

## Woran man Erfolg erkennt

- `blob verify` liefert `verified: true`
- `blob exec` liefert eine sinnvolle Ausgabe
- `blob mesh-run` liefert `worker_url`, `command` und das entfernte Ergebnis
- `ns.run` mit `blob.verify` oder `blob.exec` schreibt die erwarteten Flow-Outputs

## Typische Probleme

### `blob.exec` meldet Hash-Fehler

Dann ist der Seed veraendert oder beschaedigt.
Packe ihn neu.

### `blob.exec` fuer `ns` scheitert

Dann ist der Seed-Inhalt vermutlich kein deklaratives Nova-Programm.

### `blob mesh-run` findet keinen Worker

Dann fehlt ein passender Worker fuer die angeforderte Capability.

## Verwandte Seiten

- [NSBlobGenerator](./NSBlobGenerator.md)
- [NovaCLI](./NovaCLI.md)
- [NovaRuntime](./NovaRuntime.md)
- [ZeroCopyFederatedLearningMesh](./ZeroCopyFederatedLearningMesh.md)

# Zero-Copy Federated Learning Mesh

## Zweck

Zero-Copy Federated Learning Mesh bringt Atheria-Invarianten verteilt in den Mesh-Layer.
Statt grosse Rohdaten oder komplette Modelle zwischen Workstations zu kopieren, synchronisiert Nova-shell signierte, verifizierte Wissensupdates.

Der Fokus liegt auf:

- geringem Transferaufwand
- Integritaet der Updates
- schneller Verteilung neuer Invarianten
- same-host zero-copy ueber Shared Memory

## Kernobjekte

| Objekt | Rolle |
| --- | --- |
| `FederatedLearningMesh` | zentrale Federated-Schicht fuer Publish, Apply, Broadcast und Historie |
| `FederatedInvariantUpdate` | normiertes, signiertes Invariant-Update |
| `SignatureResolver` | HMAC-basierte Integritaetspruefung |
| `NovaZeroPool` | same-host Shared-Memory-Handles ohne teures Payload-Kopieren |
| `MeshWorkerServer` | Worker-Endpunkt fuer `/federated/apply` und Status |

## Architektur

```text
local Atheria / report
  ->
invariant payload
  ->
signature + integrity metadata
  ->
federated publish
  ->
mesh broadcast
  ->
remote apply
  ->
verified swarm memory
```

## CLI

### Status der Federated-Schicht

```powershell
mesh federated status
```

### Letzte Updates anzeigen

```powershell
mesh federated history 10
```

### Manuelles Invariant publizieren

```powershell
mesh federated publish --statement "Inter-core resonance raised" --namespace swarm --project lab --broadcast
```

### Neueste Aion-Chronik-Invariante veroeffentlichen

```powershell
mesh federated chronik-latest --broadcast
```

## Testbare Beispiele

### 1. Einfaches Publish ohne Zero-Copy

```powershell
mesh federated publish --statement "Edge anomaly detector learned new invariant" --namespace security --project guards
```

Erwartung:

- JSON mit `verified`, `update_id` und Broadcast-/Apply-Informationen

### 2. Same-host Zero-Copy ueber `zero`

```powershell
zero put federated-invariant-payload
```

Danach den Rueckgabewert `handle` und `size` verwenden:

```powershell
mesh federated publish --statement "Shared invariant" --handle <HANDLE> --size <SIZE> --type text --same-host
```

Damit wird der Payload ueber Shared Memory referenziert, nicht erneut im Klartext kopiert.

### 3. Chronik-gebundenes Schwarmgedaechtnis

```powershell
mesh federated chronik-latest --namespace atheria --project swarm --broadcast
```

Damit wird der neueste Aion-Chronik-Resonanzzustand als Federated-Update in den Mesh-Layer eingespeist.

## Integritaet und Vertrauen

Federated Updates werden nicht blind angenommen.
Die Federated-Schicht prueft:

- Signatur
- Payload-Integritaet
- semantische Struktur des Updates
- Broadcast-/Apply-Erfolg pro Worker

Damit passt die Schicht zu Nova-shells Trust- und Mesh-Sicherheitsmodell.

## Designentscheidungen

### Warum keine Rohdaten uebertragen?

Rohdaten sind teuer, sensibel und oft nicht noetig.
Fuer kollaboratives Lernen reichen haeufig verdichtete Invarianten, Statements oder Gewichts-/Signalzusammenfassungen.

### Warum same-host zero-copy?

Wenn mehrere Prozesse auf derselben Maschine laufen, ist Shared Memory guenstiger als erneutes Serialisieren.
Das ist besonders relevant fuer:

- lokale Worker
- grosse Invariant-Payloads
- schnelle Broadcast-Loops

## Typische Fehler und Fragen

### Warum wird ein Update nicht angewendet?

Typische Gruende:

- Signatur ungueltig
- Payload nicht lesbar
- Worker-Endpunkt nicht erreichbar
- Trust- oder Transportpfad nicht passend

### Wo sehe ich, ob ein Broadcast erfolgreich war?

Im Rueckgabefeld `broadcast`.
Dort stehen `applied_count`, `failed_count` und die einzelnen Antworten.

### Wann lohnt sich `--same-host`?

Wenn der Sender und der Zielworker auf derselben Maschine oder im selben lokalen Prozessverbund liegen.

## Verwandte Seiten

- [NovaMesh](./NovaMesh.md)
- [SecurityAndTrust](./SecurityAndTrust.md)
- [NovaMemory](./NovaMemory.md)
- [APIReference](./APIReference.md)
- [ExamplesAndRecipes](./ExamplesAndRecipes.md)

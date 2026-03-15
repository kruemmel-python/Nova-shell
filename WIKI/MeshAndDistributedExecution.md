# Mesh And Distributed Execution

## Zweck

Diese Seite ordnet die verteilte Ausfuehrung von Nova-shell auf Systemebene ein. Sie ist konzeptioneller als `NovaMesh`, aber betriebsnaeher als die reine Architekturuebersicht.

## Kernpunkte

- Worker melden Capabilities wie `py`, `cpu`, `ai` oder `gpu` an.
- Die Shell kann gezielt remote ausfuehren oder Entscheidungen ueber `mesh intelligent-run` treffen.
- Die deklarative Runtime kann Mesh-Worker als Ausfuehrungsziel fuer Graphschritte nutzen.
- Tokens, Labels und TLS-Profile machen den Meshpfad anschlussfaehig fuer Policy- und Tenantregeln.

## Praktische Nutzung

- Starte lokale Worker zuerst, bevor du `remote` oder `mesh run` testest.
- Verwende Labels und Tokens, wenn du mehr als einen rein lokalen Demo-Pfad dokumentierst.
- Nutze `mesh list`, um Capabilities und Heartbeats sichtbar zu machen.

## Testbare Einstiege

### Lokalen Worker starten und nutzen

```powershell
mesh start-worker --caps cpu,py
mesh list
mesh run py py 1 + 1
```

Erwartung:

- Es erscheint mindestens ein Worker mit `cpu` und `py`.
- Der Python-Befehl wird ueber den Worker ausgefuehrt.

## Typische Fragen und Fehler

### Remote-Aufruf scheitert

- Der Worker laeuft nicht.
- Die Capability des Workers passt nicht zum Befehl.
- URL, Port oder Token sind falsch.

## Verwandte Seiten

- [NovaMesh](./NovaMesh.md)
- [RuntimeAndControlPlane](./RuntimeAndControlPlane.md)
- [SecurityAndTrust](./SecurityAndTrust.md)
- [PerformanceAndScaling](./PerformanceAndScaling.md)

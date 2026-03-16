# AI OS Concept

## Zweck

Nova-shell wird als AI Operating System beschrieben, weil es Sprache, Runtime, Scheduling, Memory, Agenten und Betriebsdienste in einer Laufzeit zusammenzieht.

## Kernpunkte

- Die Shell dient als Bedienoberflaeche fuer Compute, Daten, KI und Plattformzustand.
- Die Nova-Sprache beschreibt Systeme, Daten, Agenten, Flows und Events deklarativ.
- Die Runtime uebersetzt Deklarationen in einen ausfuehrbaren Graphen und betreibt Queue, State, Events, Mesh und API.
- Das OS-Bild ist funktional zu verstehen: Orchestrierung, Beobachtbarkeit, Sicherheit und Wiederaufnahme von Arbeit.

## Praktische Nutzung

- Nutze die CLI fuer lokale Interaktion und Diagnose.
- Nutze `.ns`-Dateien fuer reproduzierbare Programme und Systemmodelle.
- Nutze `ns.control`, `mesh`, `guard` und `wiki`, wenn aus einer Runtime eine Plattform werden soll.

## Testbare Einstiege

### Vom Shellkommando zur Plattform

```powershell
doctor
ns.run .\control.ns
ns.control status
mesh start-worker --caps cpu,py
wiki build
```

Erwartung:

- Die lokale Installation ist verifiziert.
- Die deklarative Runtime ist aktiv.
- Ein Worker und die HTML-Wiki erweitern die Shell um Plattformdienste.

## Typische Fragen und Fehler

### Was das AI-OS nicht automatisch bedeutet

- Es ist kein vollstaendiges allgemeines Betriebssystem wie Windows oder Linux.
- Globale Infrastruktur, SRE und reales Multi-Region-Betriebsmodell liegen ausserhalb des Repos.
- Die Metapher beschreibt die Orchestrierungs- und Laufzeitschicht des Projekts.

## Verwandte Seiten

- [Architecture](./Architecture.md)
- [NovaRuntime](./NovaRuntime.md)
- [RuntimeAndControlPlane](./RuntimeAndControlPlane.md)
- [Research](./Research.md)

# Whitepaper: Nova-shell

## Executive Summary

Nova-shell ist eine Unified Compute and Data Orchestration Runtime fuer polyglotte Pipelines. Das System kombiniert interaktive Shell-Bedienung, deklarative Pipeline-Ausfuehrung, verteilte Reaktionsmechanismen, Observability und Security-Enforcement in einer gemeinsamen Laufzeit.

Der Kernnutzen liegt nicht in einer weiteren klassischen Kommandozeile, sondern in einer Runtime, die unterschiedliche Ausfuehrungsmodelle unter einem operativen Dach zusammenfuehrt:

- Python fuer schnelle Entwicklung und flexible Datenlogik
- C++ fuer performanzkritische Ausfuehrung
- GPU- und WASM-Pfade fuer spezialisierte Workloads
- Mesh- und Remote-Ausfuehrung fuer verteilte Systeme
- Lineage-, Observability- und Guard-Mechanismen fuer Nachvollziehbarkeit und Kontrolle

Mit Version 0.8.0 adressiert Nova-shell vor allem vier Anforderungen moderner Plattformen: geringere Integrationskosten zwischen Engines, reproduzierbare Daten- und Compute-Pipelines, kontrollierte Sicherheitsgrenzen und release-faehige Supply-Chain-Artefakte fuer Windows und Linux.

## 1. Problemstellung

Moderne Daten- und Compute-Systeme scheitern in der Praxis selten an einzelnen Algorithmen. Die eigentliche Komplexitaet entsteht an den Uebergaengen:

- Daten muessen zwischen Python, nativen Komponenten, GPU-Pfaden und verteilten Knoten bewegt werden.
- Performance-kritische Schritte werden oft manuell in andere Sprachen oder Toolchains ausgelagert.
- Reaktive Workflows, Debugging und Nachvollziehbarkeit wachsen ungeordnet ueber mehrere Systeme hinweg.
- Sicherheitsgrenzen fuer untrusted Code sind inkonsistent oder zu spaet im Lifecycle verankert.
- Releasbare Artefakte fuer Enterprise-Umgebungen benoetigen reproduzierbare Builds, Signaturen und attestierbare Metadaten.

Nova-shell setzt genau an diesen Bruchstellen an: Es vereinheitlicht Datenfluss, Ausfuehrung, Beobachtbarkeit, Security und Release-Operations in einer einzigen Runtime.

## 2. Positionierung

Nova-shell ist nicht als Ersatz fuer Bash, PowerShell oder klassische System-Shells konzipiert. Es ist eine polyglotte Runtime mit Shell-Oberflaeche.

Im Fokus stehen:

- orchestrierte Daten- und Compute-Pipelines
- Engine-Selektion und Ausfuehrungsoptimierung
- linearisierte und reaktive Ausfuehrungsmodelle
- sichere und nachvollziehbare Laufzeitentscheidungen
- produktionsfaehige Distribution auf Windows und Linux

## 3. Architekturprinzipien

Die Architektur folgt sechs Leitprinzipien:

1. Ein gemeinsames Bedienmodell
   Nova-shell bietet einheitliche Kommandos fuer lokale, native, verteilte und beobachtbare Ausfuehrung.

2. Daten zuerst
   Die Runtime behandelt Datenfluss und Speicherpfade als Kernproblem, nicht als Nebeneffekt einzelner Engines.

3. Engine-Unabhaengigkeit
   Python, C++, GPU, WASM und Remote-Ausfuehrung werden als austauschbare oder kombinierbare Execution Targets behandelt.

4. Beobachtbarkeit als Standard
   Ereignisse, Snapshots, Lineage und Bottleneck-Sicht sind keine spaeten Add-ons, sondern Bestandteil des Systems.

5. Sicherheitsgrenzen in der Runtime
   Policies, Sandboxing und Guard-Mechanismen werden direkt in den Ausfuehrungspfad integriert.

6. Release-Faehigkeit
   Ein produktionsreifes Runtime-System muss nicht nur laufen, sondern auch paketierbar, signierbar und attestierbar sein.

## 4. Systemarchitektur

Nova-shell laesst sich in vier Ebenen gliedern.

### 4.1 Execution Layer

Die Execution Layer stellt mehrere Engines unter einer gemeinsamen Routing-Oberflaeche bereit:

- `py` und `python` fuer Skript- und Ausdrucksausfuehrung
- `cpp` fuer native Kompilierung und Ausfuehrung
- `gpu` fuer GPU-nahe Berechnungspfade
- `wasm` und `cpp.sandbox` fuer kontrollierte Sandbox-Ausfuehrung
- `remote` und Mesh-Targets fuer verteilte Ausfuehrung
- `sys` fuer bewusst kontrollierte Systemaufrufe

Darauf aufbauend optimiert NovaGraph zusammenhaengende Pipelines, inklusive Fusion geeigneter C++-Expression-Stages.

### 4.2 Data Plane

Die Data Plane verbindet Compute-Stages mit moeglichst geringem Integrations- und Kopieraufwand:

- objektbasierte und textbasierte Pipeline-Weitergabe
- Shared-Memory-Handles ueber NovaZero
- Arrow-basierte IPC-Pfade fuer engine-uebergreifende Uebergabe
- Fabric- und Remote-Transfermechanismen fuer erweiterte Datenwege

Ziel ist nicht nur Performance, sondern auch eine klare Trennung zwischen Datenbewegung, Datenidentitaet und Stage-Ausfuehrung.

### 4.3 Control and Workflow Plane

Nova-shell kombiniert lineare Pipeline-Ausfuehrung mit reaktiven und verteilten Triggern:

- NovaScript fuer DSL-basierte Ausfuehrungslogik
- lokale Watch- und Reactive-Mechanismen
- NovaFlow (`dflow`) fuer verteilte Event-getriebene Workflows
- Mesh Intelligence fuer Worker-Auswahl und Remote-Offloading

Damit eignet sich das System sowohl fuer ad-hoc Ausfuehrung in einer interaktiven Shell als auch fuer dauerhafte Ereignisverarbeitung.

### 4.4 Observability and Security Plane

Observability und Security sind als Laufzeitfunktionen integriert:

- NovaLens fuer Snapshots, Replay und CAS-orientierte Lineage
- NovaPulse fuer Runtime-Status, Event-Tails und Bottleneck-Sicht
- NovaGuard fuer Policy-Enforcement, eBPF-nahe Guard-Flows und WASM-first-Isolation
- `doctor` fuer lokale Runtime- und Toolchain-Diagnose

Diese Ebene adressiert sowohl operative Fehlersuche als auch Governance-Anforderungen.

## 5. Die Enterprise-Module von Nova-shell

### 5.1 NovaZero: Unified Zero-Copy Memory Bridge

NovaZero stellt einen globalen Shared-Memory-Pool fuer Datenobjekte und Arrow-basierte Uebergaben bereit. Ziel ist eine Reduktion von Serialisierungs- und Kopierkosten beim Wechsel zwischen Python, nativen Komponenten und weiteren Engines.

Relevante Kommandos:

- `zero put <text>`
- `zero put-arrow <csv>`
- `zero get <handle>`
- `zero list`
- `zero release <handle>`

Geeignet fuer:

- grosse CSV- oder Arrow-orientierte Datenpfade
- mehrstufige Compute-Ketten mit wechselnden Engines
- speicherkritische Vorverarbeitungspipelines

### 5.2 NovaSynth: AI-Native Engine Selector and Autotuner

NovaSynth erweitert die Runtime um heuristische und telemetriegestuetzte Empfehlungen zur Engine-Selektion. In der aktuellen Auspraegung handelt es sich um eine lokale Entscheidungslogik, nicht um einen Zwang zu externen Cloud-Modellen.

Relevante Kommandos:

- `synth suggest <code>`
- `synth autotune <code>`

Ziel ist eine bessere operative Entscheidung darueber, ob ein Block in Python, C++, GPU- oder Mesh-Richtung optimiert werden sollte.

### 5.3 NovaPulse: Real-Time Observability Surface

NovaPulse stellt einen konsolidierten Observability-Einstieg fuer die Runtime bereit. Dazu gehoeren Laufzeitstatus, Ereignis-Insights und Bottleneck-Hinweise sowohl in der CLI als auch ueber die Vision-API.

Relevante Schnittstellen:

- `pulse status`
- `pulse snapshot`
- `GET /pulse/state`

NovaPulse reduziert die Luecke zwischen lokaler Shell-Ausfuehrung und operativem Runtime-Monitoring.

### 5.4 NovaFlow: Distributed Reactive Workflows

NovaFlow erweitert lokale Trigger zu einem verteilten Event-Modell. Dadurch koennen Aenderungen, Signale und Reaktionen ueber Systemgrenzen hinweg gekoppelt werden.

Relevante Kommandos und Endpunkte:

- `dflow subscribe <event> <pipeline>`
- `dflow publish <event> <payload> [--broadcast]`
- `dflow list`
- `POST /flow/event`

NovaFlow eignet sich insbesondere fuer Edge-to-Core-Szenarien, Event-Pipelines und koordinierte Reaktionen ueber mehrere Knoten.

### 5.5 NovaGuard: Sandbox Isolation and Policy Enforcement

NovaGuard adressiert das Sicherheitsproblem polyglotter Runtime-Systeme. In Nova-shell umfasst dies Policy-Kontrollen, eBPF-nahe Enforcement-Pfade und eine WASM-first-Sandbox fuer isolierte Ausfuehrung.

Relevante Kommandos:

- `guard sandbox on|off|status`
- `cpp.sandbox <cpp_code>`
- `guard ebpf-status`
- `guard ebpf-compile <policy>`
- `guard ebpf-enforce <policy>`
- `guard ebpf-release`

Der Sicherheitsnutzen liegt in kontrollierter Ausfuehrung und reduzierter Vertrauensannahme gegenueber eingebrachtem Code.

## 6. Nachvollziehbarkeit und Observability

Produktionssysteme benoetigen mehr als Logs. Nova-shell adressiert dies ueber zwei komplementaere Mechanismen:

- NovaLens fuer artefaktbezogene Nachvollziehbarkeit, Snapshot-Inspektion und Replay
- NovaPulse fuer aktuelle Betriebszustands- und Event-Sicht

Diese Trennung ist bewusst: Lens beantwortet primaer die Frage "Was ist passiert?", Pulse die Frage "Was passiert gerade?".

## 7. Security-Modell

Das Sicherheitsmodell von Nova-shell basiert auf kontrollierter Faehigkeitserweiterung statt implizitem Vollzugriff.

Wesentliche Aspekte:

- Guard-Policies koennen Systemaufrufe und riskante Pfade begrenzen.
- Sandbox-Modi reduzieren die Angriffsoberflaeche fuer untrusted Workloads.
- C++-Sandboxing ueber WASM-first reduziert Host-Abhaengigkeit im unsicheren Ausfuehrungspfad.
- Release-Artefakte koennen mit Signaturen, SBOM und Attestations ausgeliefert werden.

Wichtig ist die Abgrenzung: Nova-shell liefert Sicherheitsmechanismen, ersetzt aber keine vollstaendige Organisations-, Netzwerk- oder IAM-Architektur.

## 8. Release-, Distribution- und Supply-Chain-Modell

Nova-shell ist auf produktionsfaehige Distribution ausgelegt. Der aktuelle Release-Stack umfasst:

- Python `sdist` und `wheel`
- Nuitka-basierte Standalone-Bundles
- Windows `MSI`
- Linux `AppImage` und `.deb`
- CycloneDX-SBOM pro Build
- Subject-Checksums fuer Attestations
- Authenticode-Signierung fuer Windows-Artefakte
- detached GPG-Signaturen
- GitHub Artifact Attestations fuer Provenance und SBOM
- reproduzierbare Build-Zeitstempel ueber `SOURCE_DATE_EPOCH`

Release-Profile:

- `core` fuer eine schmale Runtime-Basis
- `enterprise` fuer erweitertes Observability-, Guard-, Arrow- und WASM-Profil

Diese Trennung erlaubt einen pragmatischen Weg zwischen kleiner Basisdistribution und erweitertem Enterprise-Funktionsumfang.

## 9. Betriebsmodell und Plattformgrenzen

Nova-shell ist derzeit fuer Windows und Linux ausgerichtet. Dabei gelten einige bewusste Rahmenbedingungen:

- `cpp` benoetigt eine lokale C++-Toolchain
- `cpp.sandbox` benoetigt eine WASM-kompatible Build-Toolchain
- GPU-Pfade bleiben absichtlich optional, da Treiber- und Vendor-Abhaengigkeiten stark variieren
- direkte Python-Builds auf Windows sollten nur mit initialisierter MSVC-Umgebung erfolgen; der Windows-Wrapper laedt `VsDevCmd` automatisch

Damit bleibt die Runtime produktionsnah, ohne die Plattformrealitaet nativer Toolchains zu verschleiern.

## 10. Typische Einsatzszenarien

### Forschung und Data Engineering

Nova-shell eignet sich fuer gemischte Datenpipelines, in denen Vorverarbeitung, native Beschleunigung und nachvollziehbare Zwischenergebnisse in einer gemeinsamen Runtime stattfinden sollen.

### Industrie und Edge-Orchestrierung

Mit reaktiven Triggern, Mesh-Offloading und verteilter Event-Zustellung kann Nova-shell lokale Signale aufnehmen und gezielt in staerkere Ausfuehrungsumgebungen weiterleiten.

### Kontrollierte Ausfuehrung von Drittlogik

Wenn fremde oder nur begrenzt vertrauenswuerdige Logik verarbeitet werden muss, bietet NovaGuard eine bessere Ausgangsbasis fuer Isolation und Richtliniendurchsetzung als eine ungeschuetzte Host-Ausfuehrung.

### Reproduzierbare Enterprise-Releases

Fuer regulierte oder auditierte Umgebungen ist wichtig, dass Artefakte nicht nur gebaut, sondern auch verifiziert und nachvollzogen werden koennen. Nova-shell integriert diese Kette direkt in den Release-Prozess.

## 11. Nicht-Ziele

Ein professionelles Whitepaper muss auch die Grenzen benennen. Nova-shell beansprucht aktuell nicht:

- vollstaendige Ersetzung allgemeiner Betriebssystem-Shells
- automatische Wunderoptimierung fuer jeden Workload
- hardwareunabhaengige GPU-Portabilitaet
- regulatorische Zertifizierung allein durch das Vorhandensein einer SBOM
- Ersatz fuer umfassende Plattform-, Cluster- oder Security-Governance

Diese Abgrenzung ist wichtig, um Nova-shell als belastbare Runtime und nicht als ueberdehntes Plattformversprechen zu positionieren.

## 12. Schlussfolgerung

Nova-shell 0.8.0 ist eine Runtime fuer Teams, die polyglotte Compute-Pfade, Datenfluss, reaktive Workflows, Observability und Security in einem gemeinsamen operativen Modell zusammenfuehren wollen.

Der Mehrwert liegt in der Kombination:

- eine gemeinsame Shell- und Runtime-Oberflaeche
- mehrere Ausfuehrungsziele unter konsistentem Routing
- integrierte Nachvollziehbarkeit und Runtime-Beobachtung
- Sicherheits- und Sandbox-Mechanismen in der Laufzeit
- release-faehige Artefakte mit SBOM, Signaturen und Attestations

Nova-shell ist damit nicht nur ein Entwicklerwerkzeug, sondern eine belastbare Laufzeitbasis fuer daten- und compute-intensive Systeme mit Produktionsanspruch.

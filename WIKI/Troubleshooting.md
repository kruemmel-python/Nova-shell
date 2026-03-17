# Troubleshooting

## Zweck

Diese Seite sammelt typische Stoerungsbilder in Nova-shell und nennt die ersten sinnvollen Diagnosekommandos.

## Erster Diagnoseblock

```powershell
doctor
ns.status
```

Diese beiden Befehle sollten fast immer zuerst laufen, bevor tiefer in Parser-, Mesh- oder Security-Themen gegangen wird.

## CLI startet nicht

- Python-Version pruefen
- Start mit `python -m nova_shell` versuchen
- Release- oder PATH-Installation pruefen

## `nova-shell` oder ein Kommando wird nicht gefunden

- Installation in der aktiven Umgebung pruefen
- bei Release-Bundles die installierte Version mit `doctor` gegen die erwartete Version abgleichen
- bei neuen Features wie `wiki` sicherstellen, dass wirklich der aktuelle Build installiert ist

## `.ns`-Datei laedt nicht

- Syntax pruefen
- Imports pruefen
- Namen von Flows und Ressourcen pruefen
- mit `ns.graph` den kompilierten Graph kontrollieren

## API antwortet nicht

- Host und Port pruefen
- Auth-Token pruefen
- Runtime- und Control-Plane-Status mit `ns.status` pruefen

## Mesh-Task laeuft nicht

- Worker-Registrierung pruefen
- Capability-Match pruefen
- Trust- und TLS-Anforderungen pruefen
- verifizieren, ob der Task lokal funktioniert, bevor er verteilt wird

## `cpp.sandbox` oder WASM-Pfade scheitern

- `doctor` auf `emcc` und `wasmtime` pruefen
- minimalen Test mit `cpp.sandbox int main(){ return 0; }` ausfuehren

## Wiki-Befehle funktionieren nicht

- pruefen, ob der installierte Build das `wiki`-Kommando bereits enthaelt
- `wiki build` im Projektroot ausfuehren
- bei Installer-Problemen Version und MSI-Stand pruefen

## Watch Monitor zeigt keine Aenderungen oder keine AI-Bewertung

Fuer den projektbezogenen Beobachter gibt es eine eigene Detailseite:

- [WatchMonitorTroubleshooting](./WatchMonitorTroubleshooting.md)

## Verwandte Seiten

- [Testing](./Testing.md)
- [OperationsAndObservability](./OperationsAndObservability.md)
- [NovaCLI](./NovaCLI.md)
- [WatchMonitorTroubleshooting](./WatchMonitorTroubleshooting.md)

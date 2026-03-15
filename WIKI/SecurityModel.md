# Security Model

## Zweck

Diese Seite beschreibt die grundlegenden Sicherheitsziele und Schutzmechanismen von Nova-shell.
Sie soll erklaeren, wie Identitaet, Isolation, Secrets und kontrollierte Ausfuehrung zusammenhaengen.

## Sicherheitsziele

- Tenant-Isolation
- RBAC
- Secret Storage
- TLS-geschuetzte Kommunikation
- Trust-Policies fuer Worker
- kontrollierte Tool- und Agentenausfuehrung

## Mechanismen

- Tokens
- Namespaces
- Rollen
- Secrets
- CA- und Zertifikatsverwaltung
- Tool-Sandboxing
- Guard- und Isolationspfade

## Praktische Pruefpunkte

### Installations- und Laufzeitfaehigkeiten

```powershell
doctor
```

### Policy- und Auth-Pfade

```powershell
ns.auth
ns.status
```

## Typische Sicherheitsfragen

### Wer darf was ausfuehren?

Das wird ueber Rollen, Namespaces, Policies und Trust-Pfade bestimmt.

### Wie wird Remote-Ausfuehrung abgesichert?

Ueber Worker-Vertrauen, Token-, Zertifikats- und Policy-Pfade.

### Wo liegen Secrets im Gesamtmodell?

Secrets gehoeren zur Plattform- und Laufzeitschicht und muessen getrennt von der eigentlichen Workflow-Logik behandelt werden.

## Verwandte Seiten

- [SecurityAndTrust](./SecurityAndTrust.md)
- [NovaMesh](./NovaMesh.md)
- [NovaAgents](./NovaAgents.md)
- [ServiceFabricAndTrafficPlane](./ServiceFabricAndTrafficPlane.md)

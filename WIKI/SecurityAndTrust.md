# Security and Trust

## Zweck

Diese Seite fasst Trust, Worker-Onboarding, Zertifikate und die operative Sicherheitsansicht zusammen.
Sie ist die Bruecke zwischen dem abstrakteren [SecurityModel](./SecurityModel.md) und den konkreten Laufzeitpfaden.

## Kernpunkte

- Tokens und Rollen
- Secrets und deren kontrollierte Nutzung
- TLS und vertrauensbasierte Worker-Kommunikation
- Trust-Policies fuer Worker und Remote-Ausfuehrung
- sichere Tool- und Agentenpfade

## Praktische Nutzung

### Sicherheitsfaehigkeiten lokal pruefen

```powershell
doctor
ns.auth
```

### Relevante Fragen

- Ist ein Worker ueberhaupt vertrauenswuerdig genug fuer die geplante Aufgabe?
- Darf ein bestimmter Agent dieses Tool oder diesen Namespace nutzen?
- Welche Rollen oder Policies muessen fuer einen Ablauf gesetzt sein?

## Abgrenzung

- Das formale Sicherheitsmodell ist in [SecurityModel](./SecurityModel.md) beschrieben.
- Die verteilte Rolle von Trust im Cluster liegt in [NovaMesh](./NovaMesh.md).
- Agentenspezifische Sicherheitsaspekte liegen in [NovaAgents](./NovaAgents.md).

## Verwandte Seiten

- [SecurityModel](./SecurityModel.md)
- [NovaMesh](./NovaMesh.md)
- [NovaAgents](./NovaAgents.md)
- [RuntimeAndControlPlane](./RuntimeAndControlPlane.md)

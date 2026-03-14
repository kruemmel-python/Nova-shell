# Security and Trust

## Zweck

Diese Seite fasst Tenant-Isolation, Authentifizierung, Zertifikate, Trust-Policies und sichere Ausfuehrung zusammen.

## Zentrale Quellen

- [nova/runtime/security.py](../nova/runtime/security.py)
- [nova/runtime/policy.py](../nova/runtime/policy.py)
- [docs/NOVA_AI_OS_ARCHITECTURE](../docs/NOVA_AI_OS_ARCHITECTURE.md)
- [examples/secure_multi_tenant.ns](../examples/secure_multi_tenant.ns)

## Themen

- Tenants und Namespaces
- Tokens und Rollen
- Secret Storage
- TLS-Profile und CA-Verwaltung
- Trust-Policies und Worker-Onboarding
- RBAC und Runtime-Policy
- sichere Mesh- und Agentenpfade

## Sinnvolle Anschlussseiten

- [MeshAndDistributedExecution](./MeshAndDistributedExecution.md)
- [ServiceFabricAndTrafficPlane](./ServiceFabricAndTrafficPlane.md)
- [OperationsAndObservability](./OperationsAndObservability.md)

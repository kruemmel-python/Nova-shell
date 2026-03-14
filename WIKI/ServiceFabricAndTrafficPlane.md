# Service Fabric and Traffic Plane

## Zweck

Diese Seite beschreibt Services, Packages, Rollouts, Discovery, Ingress und die neue Traffic-Plane.

## Zentrale Quellen

- [nova/runtime/service_fabric.py](../nova/runtime/service_fabric.py)
- [nova/runtime/traffic_plane.py](../nova/runtime/traffic_plane.py)
- [examples/service_package_platform.ns](../examples/service_package_platform.ns)
- [examples/consensus_fabric_cluster.ns](../examples/consensus_fabric_cluster.ns)

## Themen

- Package-Registry auf Runtime-Ebene
- Service-Definitionen und Reconcile
- Revisionen und Rollout-Strategien
- Service-Discovery und Ingress
- Health-Probes
- Secret-Mounts
- Traffic-Shifts und Reverse-Proxy

## Sinnvolle Anschlussseiten

- [RuntimeAndControlPlane](./RuntimeAndControlPlane.md)
- [SecurityAndTrust](./SecurityAndTrust.md)
- [OperationsAndObservability](./OperationsAndObservability.md)

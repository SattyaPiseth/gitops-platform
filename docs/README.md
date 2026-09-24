# GitOps platform documentation

This index separates current operating procedures from historical adoption
guidance. Repository manifests and pinned Helm values remain authoritative;
documentation explains their intent and safe operation but is not a second
configuration source.

## Core operating model

1. `root-applications` discovers child Applications and AppProjects.
2. Each child Application renders a pinned chart, first-party resources, or
   both through Argo CD multiple sources.
3. Automated Applications prune and self-heal. `gitlab`, `minio`, and
   `kubelet-csr-approver` require deliberate synchronization because their
   stateful or trust-path changes need an observed maintenance step.
4. Vault stores secret values; Git stores only VSO authentication and mapping
   resources. VSO creates the destination Kubernetes Secrets.
5. cert-manager creates and renews TLS Secrets. Traefik owns ingress routing,
   while each application owns its route or Ingress definition.
6. Bootstrap establishes Argo CD and the root handoff; normal operations change
   Git and allow the declared reconciliation policy to act.

## Guide map

| Guide | Current purpose |
| --- | --- |
| [Component ownership and lifecycle](component-lifecycle.md) | Bootstrap handoff, deletion boundaries, adoption and retirement procedures, and component lifecycle register |
| [Headlamp production guide](headlamp-production-gitops-guide.md) | Current architecture, access model, verification, and rollback |
| [kubelet CSR approver guide](kubelet-csr-approver-production-gitops-guide.md) | Current security policy and deliberate manual-sync operations; migration sections are retained as historical procedure |
| [Traefik dashboard operations](traefik-dashboard-gitops.md) | Dashboard ownership, Vault credential flow, availability, verification, and rotation |
| [Traefik routing concepts](traefik-routing-core-concepts.md) | HTTP/TCP routing, TLS modes, `ServersTransport`, and selection guidance |
| [Vault production bootstrap](vault-production-bootstrap.md) | Human-authorized initialization, unseal, policy/auth bootstrap, and validation |
| [Vault Secrets Operator guide](vault-secrets-operator-production-guide.md) | Secret-delivery architecture and day-two operations |
| [Certificate renewal guide](manual-certificate-renewal-guide.md) | Exceptional manual renewal and certificate-chain verification |
| [GitLab validation guide](gitlab/deployment-validation-guide.md) | Production acceptance and recovery tests, not declarative configuration |

Component-local runbooks live beside their resources under `platform/` when
their procedures are tightly coupled to that component, such as MinIO storage
and GitLab database/object-storage operations.

## Source-of-truth rules

- Application chart versions and sync policies come from
  `clusters/production/argocd/applications/`.
- Runtime overrides come from `helm-values/`.
- First-party Kubernetes resources come from `clusters/production/argocd/resources/`
  and `platform/`.
- Secret values never come from documentation examples or Git.
- A command using `kubectl apply` is bootstrap/recovery guidance, not the normal
  update path, unless its section explicitly says otherwise.
- Do not copy full manifests into guides when a link to the owning file is
  sufficient; copied manifests drift silently.

## Documentation maintenance

When ownership, a sync policy, version, path, hostname, secret mapping, or
operator command changes:

1. Update the owning declarative file.
2. Update the guide responsible for the operational contract.
3. Update this index or the root README only when navigation or the high-level
   workflow changes.
4. Run `python3 scripts/check_markdown_links.py` and `./scripts/validate.sh`.
5. Review the rendered manifests and Argo CD diff before synchronization.

Generated output, decoded Secrets, incident transcripts, and one-time live
patches do not belong in these guides.

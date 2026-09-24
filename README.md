# GitOps Platform

This repository is the declarative source of truth for platform services on the
production Kubernetes cluster. Argo CD reconciles the manifests under
`clusters/production`, the platform resources under `platform`, and the pinned
Helm overrides under `helm-values`.

## Ownership map

| Layer | Source of truth | Responsibilities |
| --- | --- | --- |
| ESXi virtual machines and guest networking | `esxi-ansible-iac` | VM hardware, guest OS, NIC configuration, and node preparation |
| Kubernetes lifecycle | Kubespray inventory and playbooks | Kubernetes, etcd, control-plane static pods, Calico, kube-proxy, and node-local DNS |
| GitOps bootstrap | `esxi-ansible-iac` | Initial Argo CD installation and root handoff; reviewed recovery path |
| Argo CD installation after handoff | This repository | `argocd-runtime` reconciles the complete pinned installation and local patches |
| Platform applications | This repository | Argo CD Applications and Projects, GitLab, Longhorn, Vault, VSO, CNPG, MinIO, Traefik, Headlamp, and monitoring |
| Secret values | HashiCorp Vault | Credentials and application secrets; secret values must never be committed to Git |
| Secret delivery | This repository and VSO | `VaultAuth` and `VaultStaticSecret` mappings that create Kubernetes Secrets |

After bootstrap handoff, `argocd-runtime` owns the full Argo CD installation,
including its controllers and CRDs. Bootstrap must stop enforcing a competing
installation; its implementation must be verified in `esxi-ansible-iac`.
cert-manager installation remains a bootstrap dependency. See the
[component ownership and lifecycle contract](docs/component-lifecycle.md) for
handoff, recovery, deletion controls, and the component register.

## Repository layout

- `clusters/production/argocd/applications`: child Argo CD Applications.
- `clusters/production/argocd/projects`: AppProject security boundaries.
- `clusters/production/argocd/resources`: resources owned by platform Applications.
- `helm-values`: pinned chart overrides, grouped by release.
- `platform`: first-party Kubernetes resources and prerequisites.
- `docs`: indexed operational, conceptual, and recovery guides.
- `scripts/validate.sh`: the local and CI validation entry point.

Start with the [documentation index](docs/README.md) to select the owning guide.
Certificate operations are documented in
[`docs/manual-certificate-renewal-guide.md`](docs/manual-certificate-renewal-guide.md).
Traefik dashboard ownership and operations are documented in
[`docs/traefik-dashboard-gitops.md`](docs/traefik-dashboard-gitops.md).

## Reconciliation model

`root-applications` discovers the child Applications and AppProjects. It
intentionally excludes its own manifest. The automated bootstrap in
`esxi-ansible-iac` performs the initial apply. The
following command is the recovery path when that handoff is
required:

```bash
kubectl apply -f clusters/production/argocd/applications/root-applications.yaml
```

Most platform Applications use automated pruning and self-healing. The primary
`gitlab` and `minio` Applications remain manually synchronized so stateful
changes can be reviewed and observed. `kubelet-csr-approver` is also manual
because it participates in the node-serving certificate trust path. Do not
enable automation for these three Applications without a component-specific
recovery, rollback, and observation review. Their prerequisite, operator, and
runner Applications may remain automated as declared in their own manifests.

Child Applications, Projects, and explicitly declared Namespaces require Argo CD
confirmation before pruning or deletion cleanup. PostgreSQL is retained on both
paths. These protections must reach live resources before a removal change;
they do not block direct Kubernetes deletion. Follow the lifecycle contract for
adoption and planned retirement.

## Validation

Required local tools are Git, Helm, Docker, Python 3 with PyYAML, yamllint, and ShellCheck. Run the
same checks used by GitHub Actions:

```bash
./scripts/validate.sh
```

The script checks Git patches, YAML, lifecycle deletion boundaries and their
regression tests, validates shell and Kubernetes
resources, renders every pinned Helm release, verifies the Traefik GitLab Shell
entrypoint and dashboard wiring, and scans Git history for secrets.

Validation downloads Helm repository indexes and may pull pinned validation
container images. Secret values are not required and must not be rendered into
this repository.

## Change workflow

1. Create a focused branch and edit the declarative source.
2. Run `./scripts/validate.sh`.
3. Review `git diff --check` and the complete diff.
4. Push the branch and require the validation workflow to pass.
5. Merge through review.
6. Observe Argo CD, workload readiness, Kubernetes events, and storage health.

Avoid helpers that stage and push every worktree change. Stateful Applications
must be synchronized deliberately, without pruning, until their health checks
have passed.

## Operational boundaries

An Argo CD or Headlamp connection warning is not automatically an application
failure. Check the Kubernetes API and etcd first. Control-plane, datastore, VM,
and hypervisor repairs belong in Kubespray or `esxi-ansible-iac`; application
configuration belongs here.

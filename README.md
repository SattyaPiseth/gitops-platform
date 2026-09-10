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
| GitOps bootstrap | Manual, documented bootstrap | Initial Argo CD installation and the first `root-applications` apply |
| Platform applications | This repository | Argo CD Applications and Projects, GitLab, Longhorn, Vault, VSO, CNPG, MinIO, Traefik, Headlamp, and monitoring |
| Secret values | HashiCorp Vault | Credentials and application secrets; secret values must never be committed to Git |
| Secret delivery | This repository and VSO | `VaultAuth` and `VaultStaticSecret` mappings that create Kubernetes Secrets |

Argo CD's runtime configuration is reconciled by `argocd-runtime`. The Argo CD
installation itself and cert-manager are currently bootstrap dependencies. Any
change to their ownership must be documented here before adding another
installer or controller.

## Repository layout

- `clusters/production/argocd/applications`: child Argo CD Applications.
- `clusters/production/argocd/projects`: AppProject security boundaries.
- `clusters/production/argocd/resources`: resources owned by platform Applications.
- `helm-values`: pinned chart overrides, grouped by release.
- `platform`: first-party Kubernetes resources and prerequisites.
- `docs`: operational and recovery guides.
- `scripts/validate.sh`: the local and CI validation entry point.

Certificate operations are documented in
[`docs/manual-certificate-renewal-guide.md`](docs/manual-certificate-renewal-guide.md).

## Reconciliation model

`root-applications` discovers the child Applications and AppProjects. It
intentionally excludes its own manifest, so a one-time bootstrap apply is
required:

```bash
kubectl apply -f clusters/production/argocd/applications/root-applications.yaml
```

Most platform Applications use automated pruning and self-healing. GitLab and
MinIO remain manually synchronized so stateful changes can be reviewed and
observed. Do not enable automated pruning for either application without a
specific recovery and rollback review.

## Validation

Required local tools are Git, Helm, Docker, Python 3, yamllint, and ShellCheck. Run the
same checks used by GitHub Actions:

```bash
./scripts/validate.sh
```

The script checks Git patches and YAML, validates shell and Kubernetes
resources, renders every pinned Helm release, verifies the Traefik GitLab Shell
entrypoint, and scans Git history for secrets.

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

# Component ownership and lifecycle

This is the operating contract for the existing app-of-apps architecture.
Application manifests remain authoritative for sources, versions, destinations,
and sync policies. This guide defines ownership and the evidence required to
operate those resources. It does not certify live adoption or recovery.

## Ownership rules

- One Argo CD Application owns each desired Kubernetes resource. An operator
  owns the resources it generates from that declaration. These are distinct
  responsibilities, not competing deployment paths.
- Chart versions come from Application manifests; runtime settings come from
  their referenced values files. CI renders and checks configuration; Argo CD
  deploys it. Duplicated render inputs in the validation script remain a
  follow-up task.
- Vault owns external credential values; VSO delivers them. cert-manager owns
  issued TLS Secrets. GitLab's shared-secrets hook owns its generated internal
  Secrets. Internal encryption material needs protected backup custody; a
  newly generated value is not a restored value.
- Git review authorizes configuration changes. Manual synchronization is an
  operator-controlled trigger within the same Argo CD deployment path.
- Bootstrap and recovery are explicit exceptions to steady-state deployment.
  They restore the same declared configuration, not a competing installation.

## Argo CD bootstrap and ownership handoff

The authoritative installation source is
[`resources/kustomization.yaml`](../clusters/production/argocd/resources/kustomization.yaml).
It includes the full upstream installation, including CRDs and controllers.
[`argocd-runtime`](../clusters/production/argocd/applications/argocd-runtime.yaml)
reconciles that installation and its local patches after handoff.

| Phase | Owner | Completion condition |
| --- | --- | --- |
| Foundation | `esxi-ansible-iac` and Kubespray | Nodes, Kubernetes API, networking, and storage prerequisites are available |
| Initial Argo CD installation | External bootstrap | Install the reviewed Git revision's Argo CD Kustomization; provision access credentials outside Git |
| Root handoff | External bootstrap | Establish the platform AppProject needed by the root, then apply the root Application from the same revision |
| Steady state | `argocd-runtime` and `root-applications` | Runtime owns installation resources; root owns child Applications and Projects |
| Installation upgrades | Git review, then `argocd-runtime` | Review the upstream change and rendered diff; verify controller and reconciliation health |
| Recovery | Designated platform operator using bootstrap | Restore the reviewed configuration and required credentials, then return ownership to Argo CD |

The external bootstrap repository was not changed by this milestone. Verify its
implementation before declaring handoff complete: recurring Ansible, Helm, or
kubectl tasks must not keep enforcing an independent Argo CD version or spec.
Do not use two controllers to manage the installation after adoption.

The root excludes its own manifest. Its initial apply, later definition updates,
and recovery therefore belong to the bootstrap path. Review the change and use
that path deliberately; changing its file alone does not update the live root.
AppProjects become root-owned after the initial platform project is established.
cert-manager installation remains an external bootstrap responsibility.

Before recording handoff completion:

1. Record the reviewed Git commit and bootstrap execution responsible for it.
2. Compare the rendered installation against live resources, tracking
   annotations, and managed fields. Resolve any old installer ownership before
   reconciliation; do not blindly replace live objects or credentials.
3. Verify Argo CD can fetch all configured sources and reconcile Applications.
4. Verify the bootstrap installer no longer runs a competing update loop.
5. Record how repository credentials, Argo CD credentials, and cluster access
   are recovered outside this repository.

## Deletion boundaries

| Boundary | Declared control | Effect through Argo CD |
| --- | --- | --- |
| Every child Application and AppProject | `Prune=confirm,Delete=confirm` metadata annotation | Root pruning and root deletion cleanup require confirmation before removing these resources |
| Every explicitly declared Namespace | `Prune=confirm,Delete=confirm` metadata annotation | Its owning Application requires confirmation before namespace pruning or deletion cleanup |
| CNPG Cluster declarations | `Prune=false,Delete=false` metadata annotation | Retain the database declaration during pruning and Application deletion cleanup |

Resource annotations act at the **owning Application's** boundary. For example,
GitLab Application removal is governed by the root; GitLab Namespace removal is
governed by `gitlab-prerequisites`. An annotation on the child Application does
not prevent a direct API deletion of that child by an administrator.

The controls preserve existing automatic update/self-heal policies and existing
finalizers. They do not make GitLab's automated dependencies manual. Applications
without resource finalizers may leave resources orphaned when removed; finalizer
presence must be checked in the live removal plan rather than assumed uniform.

### Protection limits

- These settings are effective only after their annotations reach live objects.
- A direct Kubernetes deletion, namespace deletion, CRD deletion, storage-system
  deletion, or forced finalizer removal can bypass relevant Argo CD boundaries.
  Kubernetes and Argo CD access controls remain necessary.
- Generated PVCs, chart-generated resources, and namespaces created only with
  `CreateNamespace=true` are not all protected individually by this milestone.
  Confirming an Application removal may authorize cleanup of its managed data
  resources. Inspect the actual resource graph and reclaim/retention policies.
- `Prune=false` does not protect against deletion cleanup; `Delete=false` does
  not protect against namespace deletion. PostgreSQL has both options, and its
  containing Namespace has a separate confirmation gate.
- Confirmation applies to an owning Application operation; it is not a
  per-resource business approval. Review every pending deletion in that scope.
- A pending prune can leave an Application OutOfSync or an operation waiting.
  This is expected and needs operator review, not removal of the guard.

See the upstream [sync-option semantics](https://argo-cd.readthedocs.io/en/stable/user-guide/sync-options/)
and [Application deletion semantics](https://argo-cd.readthedocs.io/en/stable/user-guide/app_deletion/).

### Adoption of these controls

1. Merge and synchronize the protection changes before any later removal commit.
2. Verify the root has applied annotations to its child Applications and Projects.
3. Verify each owning Application has applied Namespace and database protections.
4. Check that no old `argocd.argoproj.io/deletion-approved` annotation remains on
   an owning Application; investigate and clear stale operational approvals.
5. Record the Git revision and live verification in the change record. Test the
   deletion behavior with disposable resources in a non-production environment.

Read-only checks include:

```bash
kubectl get application gitlab -n argocd -o jsonpath='{.metadata.annotations.argocd\.argoproj\.io/sync-options}'
kubectl get namespace gitlab -o jsonpath='{.metadata.annotations.argocd\.argoproj\.io/sync-options}'
kubectl get cluster.postgresql.cnpg.io gitlab-postgresql -n gitlab -o jsonpath='{.metadata.annotations.argocd\.argoproj\.io/sync-options}'
```

### Planned retirement

1. Identify the owner, all consumers, finalizers, namespaces, volumes, CRDs, and
   external dependencies. Record the exact resources to retire and retain.
2. Obtain a current independent backup and successful restore evidence for
   stateful data and required encryption keys. Stop or migrate writers.
3. Prepare a focused removal change and inspect the owning Application's complete
   diff. Do not combine unrelated removals into the same approval operation.
4. After review, an authorized operator confirms the specific Argo CD operation.
   Never commit `argocd.argoproj.io/deletion-approved` timestamps to Git. Inspect
   and clear operational approval metadata after the operation.
5. Database destruction remains a separate procedure: confirmation cannot override
   `Prune=false,Delete=false`. A retained database needs an explicitly assigned
   owner, or a separately reviewed retirement and access-controlled deletion.
6. Retire namespaces only after inventories confirm that all occupants are
   intentionally retired. Remove operator CRDs only after their custom resources
   have been handled; remove AppProjects after their Applications.
7. Verify retained data, revoked identities, released capacity, and monitoring.
   Record what was removed and who owns everything retained.

## Component lifecycle register

The platform maintainers named by [CODEOWNERS](../.github/CODEOWNERS) are the
repository review owners. The operational change record must name the person
performing and accepting a deployment or recovery. The deployment owner below
is the reconciler; generated workloads remain the corresponding operator's job.
Current sync policies must be read from the linked manifests.

| Component | Desired source and deployment owner | Readiness and lifecycle evidence |
| --- | --- | --- |
| Root and Projects | [Root Application](../clusters/production/argocd/applications/root-applications.yaml); bootstrap owns the root itself | Source access, project boundaries, child discovery, handoff record; confirm child removal |
| Argo CD installation | [argocd-runtime](../clusters/production/argocd/applications/argocd-runtime.yaml), runtime Kustomization | Controllers and repository rendering healthy; credential recovery; installation upgrades and retirement reviewed |
| GitLab | [gitlab](../clusters/production/argocd/applications/gitlab.yaml), GitLab values | Dependencies ready, migrations complete, login/Git/CI functional; internal Secret backup and tested restore; manual sync |
| GitLab supporting resources | [gitlab-prerequisites](../clusters/production/argocd/applications/gitlab-prerequisites.yaml), `platform/gitlab` | TLS, VSO delivery, network flows verified; namespace retirement separate from individual resources |
| PostgreSQL | [Cluster](../platform/gitlab/database/cluster.yaml) through `gitlab-prerequisites`, then CNPG | Primary/replicas and queries healthy; credential adoption, backup schedule and restore evidence; retained on removal; dedicated Application remains follow-up |
| CNPG operator | [cnpg](../clusters/production/argocd/applications/cnpg.yaml) | CRDs/controller ready before Cluster creation; compatible upgrades; no operator retirement while dependent Clusters remain |
| Backup plugin | [plugin-barman-cloud](../clusters/production/argocd/applications/plugin-barman-cloud.yaml) | Plugin readiness does not prove backups; database integration, target, schedules, alerts, retention and restores remain required |
| Redis operator | [redis-operator](../clusters/production/argocd/applications/redis-operator.yaml) | CRDs/controller ready; supported workload upgrades; remove after dependent custom resources |
| Redis/Sentinel | [gitlab-redis](../clusters/production/argocd/applications/gitlab-redis.yaml), Redis values | Authenticated primary discovery and failover; coordinated password adoption; persistent-data recovery and retirement plan |
| Runner | [gitlab-runner](../clusters/production/argocd/applications/gitlab-runner.yaml), Runner values | Real job and artifact delivery; token rotation/revocation; drain jobs before removal |
| MinIO operator | [minio-operator](../clusters/production/argocd/applications/minio-operator.yaml) | Controller/CRDs ready; compatibility with Tenant; retire only after Tenants |
| MinIO prerequisites | [minio-prerequisites](../clusters/production/argocd/applications/minio-prerequisites.yaml) | TLS, root Secret and storage class ready; coordinate credential rotation; protect Namespace |
| MinIO Tenant | [minio](../clusters/production/argocd/applications/minio.yaml), Tenant values and routes | Manual sync; authenticated bucket operations; identities, independent copy and restore required before production acceptance |
| Vault | [vault](../clusters/production/argocd/applications/vault.yaml), Vault values | Initialized/unsealed quorum, TLS and authentication; external key custody, snapshots and tested recovery; namespace protection |
| Vault secret delivery | [vault-secrets-operator](../clusters/production/argocd/applications/vault-secrets-operator.yaml) plus mappings owned by consumers' Applications | Auth valid, expected Secret keys, provider/client rotation and reload tested; remove consumers before delivery identities |
| Longhorn | [longhorn](../clusters/production/argocd/applications/longhorn.yaml) | Volume and replica health/capacity; supported upgrades, independent backups; drain or migrate consumers before storage retirement |
| Monitoring CRDs | [kube-prometheus-stack-crds](../clusters/production/argocd/applications/kube-prometheus-stack-crds.yaml) | Compatibility with operator and custom resources; dedicated CRD owner; no automatic pruning configured |
| Monitoring | [kube-prometheus-stack](../clusters/production/argocd/applications/kube-prometheus-stack.yaml) | Scrapes, alerts and authentication; credential reload, persistent-data recovery and retention policy |
| Traefik | [traefik](../clusters/production/argocd/applications/traefik.yaml) | TLS, HTTP and SSH routes; certificate/auth reload; plan consumer cutover before ingress removal |
| Headlamp | [headlamp](../clusters/production/argocd/applications/headlamp.yaml) | TLS, login and RBAC; credential/certificate renewal; Namespace confirmation |
| CSR approver | [kubelet-csr-approver](../clusters/production/argocd/applications/kubelet-csr-approver.yaml) | Manual trust-policy changes; expected approvals/rejections; documented node certificate renewal alternative before removal |
| cert-manager | External bootstrap installs controller; consumer Applications own Certificate declarations | Issuer and leaf readiness; renewal, CA trust overlap, key recovery; no second installer here |

## Lifecycle acceptance and remaining work

Create, Update, Ready, Rotate, Backup, Restore, and Delete are recurring lifecycle
checks. Ready is evaluated after creation, updates, rotation, and restoration.
Stateless components may recover from Git plus separately protected credentials;
stateful components require data recovery as well.

Each change record must distinguish:

- **Declared:** manifests and procedures describe the intended behavior.
- **Enforced:** deployed controllers and access policies implement it.
- **Proven:** an observed test demonstrates the outcome, with revision, operator,
  date, and evidence stored in the operational record outside this repository.

This milestone declares deletion guards and the ownership handoff, with local
policy regression checks. Live adoption, external bootstrap implementation, RBAC,
branch protection, and destructive tests are not established by a passing CI run.
Remaining milestones are dependency readiness, a careful PostgreSQL ownership
transfer, full credential rotation, independent backup/restore testing, deriving
validation inputs from Applications, and complete rendered-resource validation.
Existing operational guides remain entry points, not proof that their acceptance
checks have been executed. In particular, the two Vault policy procedures need
consolidation before treating them as one reproducible configuration path.

## Protection milestone acceptance record

Copy this template into the external change record. Its initial status is
**unverified**; it is not evidence that CI, destructive tests, or live adoption
have occurred. Keep credentials, decoded Secrets, and raw incident transcripts
out of Git. Link to access-controlled evidence instead.

| Record field | Value to supply |
| --- | --- |
| Change / pull request | Reference |
| Reviewed commit and deployed commit | Exact SHAs; explain and revalidate any difference |
| Responsible operator and reviewer | Names |
| Disposable test environment | Cluster identity, Argo CD version, operator versions, and test revision |
| Production adoption target | Cluster identity and affected Applications |
| Execution dates | Timestamps with timezone |
| Milestone status | Unverified until all gates below pass |

| Acceptance gate | Required evidence | Initial status |
| --- | --- | --- |
| Full validation | Successful complete CI run linked to the reviewed revision, including Docker-based checks | Unverified |
| Disposable deletion tests | Expected and observed outcomes for every scenario below, including retained-resource inventory | Unverified |
| Review and merge | Focused protection PR, approval record, and resulting commit | Unverified |
| Live adoption | Reconciled revisions and live deletion annotations for every protected Application, Project, Namespace, and CNPG Cluster | Unverified |
| Operational approvals | No unexplained or stale deletion-approval annotations on owning Applications | Unverified |
| Repository governance | Effective required checks/reviews, direct-push restrictions, and enumerated bypass permissions | Unverified |
| Bootstrap handoff | Reviewed `esxi-ansible-iac` revision, relevant tasks/schedules, and evidence that no competing installation reconciliation continues | Unverified |

### Disposable deletion test matrix

Use an isolated cluster with disposable data and the deployed Argo CD version.
Apply and verify the guards before each test. Reset the fixture and remove old
operational approvals between scenarios so one confirmation cannot invalidate
another test. Record the owning Application, finalizers, resource identities,
expected result, actual result, and evidence reference for each scenario.

| Scenario | Expected result before confirmation | Additional evidence |
| --- | --- | --- |
| Remove a guarded child Application from the parent's Git source | Parent pruning waits for confirmation; child and its resources remain | Child annotation is evaluated by the parent even if the child uses manual sync |
| Delete a disposable parent with a resource finalizer | Cleanup of guarded children/Projects waits for confirmation | Inventory every guarded child; do not assume unguarded resources are retained |
| Directly delete a disposable child with a resource finalizer | Its own metadata guard does not stop the direct API request; cleanup follows its managed resources' protections | Demonstrate the boundary explicitly; this is not a successful direct-deletion prevention test |
| Remove a guarded Namespace from its owning source | Namespace pruning waits for confirmation | Namespace and its occupants remain before approval |
| Delete the Namespace's owning Application with a resource finalizer | Namespace deletion cleanup waits for confirmation | Other unguarded resources may be removed; Namespace protection is not workload-wide retention |
| Remove the CNPG Cluster declaration from Git | `Prune=false` retains the Cluster | Record unchanged Cluster identity and database availability |
| Delete a disposable database-owning Application with a resource finalizer | `Delete=false` retains the Cluster | Keep its Namespace outside this deletion scope; verify database data and retained storage independently |
| Confirm one focused disposable removal | Only the reviewed operation proceeds according to remaining guards | Inspect the full pending deletion set; verify retained resources and clear the approval afterward |

For each retained database, verify a known test record through a database query;
object existence alone is insufficient. PostgreSQL retention tests do not prove
backup restoration. Do not delete its Namespace or CRD to test these Argo CD
retention settings: those are separate deletion paths that can bypass them.

### Open items and completion

For every failed or unverified gate, record an owner, next action, and evidence
needed to close it. Do not replace a missing test with a checked documentation
box. Any changed configuration after testing requires an impact review and
appropriate revalidation against the final deployed revision.

The reviewer may mark this milestone complete only after all acceptance gates
pass and live adoption is recorded. Backup/restore proof is the next milestone:
PostgreSQL ownership remains unchanged until recovery tests cover PostgreSQL,
GitLab, and required encryption material from independent backups.

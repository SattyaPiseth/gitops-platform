# GitLab CE 19.2.7 production patch readiness

## Master gate and scope

`Recovery Ready → Platform Healthy → Rehearsal Passed → Chart Validated → Maintenance Approved → Upgrade → Post-Validation Passed`

**Current assessment: NO-GO.** This document is a plan, not evidence that its
checks passed. The repository review was performed on 2026-09-25. Live health,
migration completion, full backup coverage, separate recovery-secret custody,
external copies, and isolated restoration require fresh evidence.

Scope: GitLab CE **19.2.6 → 19.2.7**, Helm chart **10.2.6 → 10.2.7**.
GitLab 19.3/19.4 and changes to CNPG, PostgreSQL, Redis, MinIO, networking,
credentials, and scheduling are outside this patch. Recovery remediation must
be separately reviewed. No production operation is authorized by this guide.

- **GO:** every mandatory pre-upgrade gate passes and maintenance is approved.
- **NO-GO:** recovery, database, storage, migration, or platform checks fail or
  lack evidence. An archive upload or exit code zero is insufficient.
- Reverting chart 10.2.7 to 10.2.6 is **not an assumed-safe rollback after database
  migrations**. Recovery must account for compatible database and object data.
- Docker-dependent validation runs in CI or a dedicated host. Do not install
  or enable Docker on the containerd-based Kubernetes control-plane node.

Command labels:

| Label | Meaning |
| --- | --- |
| READ-ONLY | Inspect state without deliberate configuration/data changes |
| VALIDATION | Run checks; may create local reports or consume application resources |
| CHANGE | Writes application/infrastructure data; requires explicit approval |
| RECOVERY | Restores or overwrites data; requires explicit approval and isolation |

Never print Secret values, `.s3cfg`, tokens, or decoded credentials. Store logs,
rendered manifests and recovery evidence in restricted storage, not this repo.

## Findings and repository baseline

| Source | Observed declaration and implication |
| --- | --- |
| [GitLab Application](../../clusters/production/argocd/applications/gitlab.yaml) | Chart 10.2.6, manual sync, values from Git `main`; review the precise Git revision before sync |
| [Version record](../../helm-values/gitlab/VERSION) | GitLab 19.2.6 / chart 10.2.6 |
| [GitLab values](../../helm-values/gitlab/values.yaml) | CE, Traefik, upgradeCheck disabled, zero-surge Webservice/Sidekiq rollout, slow Sidekiq startup allowance |
| [Production values](../../helm-values/gitlab/values-production.yaml) | External PostgreSQL and Redis/Sentinel; distinct Rails, Registry and Toolbox S3 secrets |
| [Validation script](../../scripts/validate.sh) | Renders 10.2.6; includes Docker-based schema and secret scanning |
| [Root Application](../../clusters/production/argocd/applications/root-applications.yaml) | Auto-syncs child Application definitions |
| [Prerequisites](../../clusters/production/argocd/applications/gitlab-prerequisites.yaml) | Auto-sync/prune/self-heal; manual GitLab sync does not freeze prerequisites |
| [CNPG cluster](../../platform/gitlab/database/cluster.yaml) | PostgreSQL 17.9 by digest, three instances, 50 GiB data + 10 GiB WAL each, Longhorn, supervised primary updates; no backup configuration in this manifest |
| [Redis values](../../helm-values/gitlab/redis-values.yaml) | Three Redis and three Sentinel instances, 7.2.16, persistent Longhorn storage |
| GitLab Gitaly values | 50 GiB Longhorn PVC; live replica/topology and free capacity need verification |
| [MinIO values](../../helm-values/minio/values.yaml) | Four 25 GiB volumes; explicitly classified pre-production |
| [MinIO storage class](../../platform/minio/prerequisites/storageclass.yaml) | One Longhorn replica per volume, strict-local placement, Retain policy; not independent recovery storage |
| [VSO resources](../../platform/gitlab/vault/gitlab-vault-static-secrets.yaml) | Backup config from KV v2 mount `kv`, path `gitlab/object-storage/backup`; no Toolbox restart target for this Secret |
| [AppProject](../../clusters/production/argocd/projects/gitlab-project.yaml) | Chart-generated Rails secret excluded from orphan warnings; this does not back it up |

The earlier live review reported source-bucket 403 errors. That evidence is
historical, not a fresh live check. The current [object-storage guide](../../platform/gitlab/object-storage/README.md)
still limits the backup identity to archive/staging buckets; source read access
and effective inherited permissions need a separate review. Previously drafted
backup policies were removed and must not be treated as deployed controls.

### Disabled upgrade check and chart hooks

`upgradeCheck.enabled: false` disables the chart's upgrade-path safeguard.
Leave it unchanged until its intended behavior is tested separately.

Argo CD renders Helm templates and manages lifecycle itself. Supported Helm
pre-install/pre-upgrade hooks map to PreSync; a sync is not a native Helm upgrade.
Review migration/shared-secrets Jobs, hook annotations, ordering, recreation,
cleanup, and RBAC using the exact target chart and installed Argo CD version.
Check for mixed Argo/Helm hook annotations. Selective resource sync does not run
hooks. Application deletion-confirmation annotations do not automatically
protect all child PVCs or Secrets.

Sources: [Argo Helm semantics](https://argo-cd.readthedocs.io/en/stable/user-guide/helm/),
[resource hooks](https://argo-cd.readthedocs.io/en/stable/user-guide/resource_hooks/).

## Operational runbook

For every stage record **Purpose → Command → Expected Result → PASS/FAIL →
Action if Failed**, with operator, timestamp, context, Git SHA and evidence link.
All commands below are future procedures; none were run to create this guide.

Set `PROD_CONTEXT` to the independently verified production context. Resolve
`PRIMARY`, `MIGRATION_JOB`, `BACKUP_ID`, and file paths from reviewed evidence;
do not copy example placeholders into a production command.

### 1. Current baseline

**Purpose:** establish deployed and declared identity.

**Command — READ-ONLY:**

```bash
git status --short --branch
cat helm-values/gitlab/VERSION
kubectl config get-contexts
kubectl --context "$PROD_CONTEXT" version
kubectl --context "$PROD_CONTEXT" -n argocd get applications gitlab gitlab-prerequisites
kubectl --context "$PROD_CONTEXT" -n gitlab get deployments,statefulsets
kubectl --context "$PROD_CONTEXT" -n gitlab exec deploy/gitlab-toolbox -c toolbox -- \
  gitlab-rake gitlab:env:info
```

**Expected Result:** CE 19.2.6/chart 10.2.6, correct context, healthy baseline,
no unexplained drift. **PASS/FAIL:** record version and health evidence.
**Action if Failed:** stop and reconcile discrepancies.

### 2. Recovery readiness gate

**Purpose:** establish usable recovery, not merely backup presence.

**Command — READ-ONLY:** review signed-off backup logs, component manifest,
external-copy checksum, secret-custody record and isolated restore report.
Inspect original Rails Secret metadata without its payload:

```bash
kubectl --context "$PROD_CONTEXT" -n gitlab get secret gitlab-rails-secret \
  -o custom-columns=NAME:.metadata.name,CREATED:.metadata.creationTimestamp
```

**Expected Result:** all required data captured; original Rails encryption
secrets protected separately; external copy downloaded and verified; same-version
restore succeeded. **PASS/FAIL:** existence alone fails to prove recovery.
**Action if Failed:** remediate separately; keep upgrade closed. Protect SSH
host keys and document TLS/CA and independent Vault recovery as well.

### 3. Platform preflight

**Purpose:** confirm dependencies, capacity and migrations.

**Commands — READ-ONLY:**

```bash
kubectl --context "$PROD_CONTEXT" get nodes
kubectl --context "$PROD_CONTEXT" -n gitlab get pods,pvc,pdb,jobs
kubectl --context "$PROD_CONTEXT" -n minio-system get pods,pvc
kubectl --context "$PROD_CONTEXT" -n longhorn-system get volumes.longhorn.io
kubectl --context "$PROD_CONTEXT" -n gitlab describe cluster.postgresql.cnpg.io gitlab-postgresql
kubectl --context "$PROD_CONTEXT" -n gitlab get cluster.postgresql.cnpg.io gitlab-postgresql \
  -o jsonpath='{.status.currentPrimary}{"\n"}'
kubectl --context "$PROD_CONTEXT" -n gitlab exec deploy/gitlab-toolbox -c toolbox -- \
  gitlab-rake db:migrate:status
```

With `PRIMARY` set to the confirmed current primary:

```bash
kubectl --context "$PROD_CONTEXT" -n gitlab exec "$PRIMARY" -c postgres -- \
  psql -U postgres -d gitlabhq_production -c \
  'SELECT count(*) AS incomplete FROM batched_background_migrations WHERE status NOT IN (3, 6);'
```

Also inspect Admin → Monitoring → Background migrations. Repeat checks for each
configured GitLab database. Verify actual CNPG replication/lag using approved
monitoring or the installed CNPG status plugin; pod readiness alone is insufficient.

**Expected Result:** three healthy DB instances, streaming replicas without growing
lag, no pending/failed migrations, zero incomplete background migrations. Verify
Redis/Sentinel quorum and primary discovery, MinIO health, Gitaly repository
access, TLS/VSO health, PVC availability and measured data/WAL/staging free space.
No active backup/restore, storage rebuild, failover, or competing maintenance.

**PASS/FAIL:** Running pods and Bound PVCs alone do not pass the gate.
**Action if Failed:** stop and resolve the failing dependency separately. Do not
force-finalize migrations or change database versions as part of this patch.

### 4. Backup/restore validation

**Purpose:** verify source access and produce a complete acceptance backup.

**Command — READ-ONLY:**

```bash
kubectl --context "$PROD_CONTEXT" -n gitlab exec deploy/gitlab-toolbox -c toolbox -- sh -eu -c '
  for bucket in gitlab-registry gitlab-uploads gitlab-artifacts \
    gitlab-lfs gitlab-packages gitlab-backups
  do
    s3cmd --config=/etc/gitlab/.s3cfg --limit=1 ls "s3://$bucket/" >/dev/null
  done
'
```

Listing is not proof of object reads: read representative existing objects into
`/dev/null` using the same identity. Inventory historical MR diffs, Terraform
state and disabled-feature buckets using authorized administration. Approve
exclusions only with evidence; 403 does not mean absent or empty.

**Command — CHANGE, separate backup approval required:**

```bash
set -o pipefail
umask 077
kubectl --context "$PROD_CONTEXT" -n gitlab exec deploy/gitlab-toolbox -c toolbox -- \
  backup-utility 2>&1 | tee "$BACKUP_LOG"
```

The plain command is a template: add only explicitly reviewed skip arguments
for proven-unneeded components. Never ignore default-bucket failures. Take the
acceptance backup in a rehearsed quiet window for cross-component consistency.

**Commands — VALIDATION, protected host:**

```bash
sha256sum "$ARCHIVE"
tar -tf "$ARCHIVE"
tar -xOf "$ARCHIVE" backup_information.yml
```

Use the exact metadata member path from the tar listing. Inspect version,
component coverage, DB/repository contents and nested gzip/tar integrity. Verify
checksums against a downloaded external copy; multipart ETags are not universal
content checksums. Keep secret recovery material separate from the archive.

**Expected Result:** DB/repositories and all required object buckets succeed;
zero 403/AccessDenied and unexplained skips; external copy and original Rails
secret custody verified. Empty components require inventory evidence.
**PASS/FAIL:** uploaded archive or exit zero alone never passes.
**Action if Failed:** reject the backup and repair coverage before proceeding.

### 5. Isolated rehearsal

**Purpose:** prove restore and exact patch behavior.

**Command — RECOVERY, isolated context only:**

```bash
kubectl --context "$RESTORE_CONTEXT" -n "$RESTORE_NAMESPACE" \
  exec -it deploy/gitlab-toolbox -c toolbox -- \
  backup-utility --restore -t "$BACKUP_ID"
```

Before execution: verify the restore context is not production; provision CE
19.2.6/chart 10.2.6, original Rails encryption secrets, separate credentials and
storage. Block production endpoints, SMTP, integrations and runners. Stop DB
clients and control test reconciliation/HPA per the official restore procedure.
Ensure extraction capacity and database restore privileges are sufficient.

**Expected Result:** recovery from the external copy works; subsequent approved
patch to CE 19.2.7/chart 10.2.7 passes the same functional checks as production.
Measure migration/startup duration and recovery time.
**PASS/FAIL:** data recovery plus patch rehearsal must both pass.
**Action if Failed:** fix procedure and repeat; no production upgrade.

### 6. Chart render/diff review

**Purpose:** review all target changes and validate the future PR.

**Commands — VALIDATION, CI/dedicated checkout only:**

```bash
umask 077
REVIEW_DIR=$(mktemp -d)
for version in 10.2.6 10.2.7; do
  helm template gitlab gitlab --repo https://charts.gitlab.io/ \
    --version "$version" --namespace gitlab --kube-version 1.35.4 \
    -f helm-values/gitlab/values.yaml \
    -f helm-values/gitlab/values-production.yaml \
    > "$REVIEW_DIR/gitlab-$version.yaml"
done
diff -u "$REVIEW_DIR/gitlab-10.2.6.yaml" "$REVIEW_DIR/gitlab-10.2.7.yaml"
bash scripts/validate.sh
```

Run against the reviewed future patch checkout with the validation pin updated.
Diff exit code 1 means differences exist, not that rendering failed. Keep renders
restricted; review them without publishing generated secrets. Match relevant
API capabilities to Argo CD's render and check its actual desired manifests.

**Expected Result:** explain every image, migration/hook, RBAC, probe, resource,
PVC, ingress and Secret delta. No accidental credential regeneration, destructive
storage replacement, networking change, or dependency upgrade. Full CI passes.
**PASS/FAIL:** unexplained differences or incomplete CI are failures.
**Action if Failed:** fix the future PR, not production. Do not bypass missing
validation tools by installing Docker on the control-plane node.

### 7. Production maintenance steps

**Purpose:** execute only the approved patch after every prerequisite passes.

**Commands — READ-ONLY:**

```bash
argocd app get gitlab
argocd app diff gitlab
```

Verify the Argo server/destination, chart target and exact values Git SHA. Freeze
unrelated changes to `main` and prerequisites during the window. A moving `main`
reference must not introduce unreviewed values between approval and sync.
Confirm fresh recovery evidence, quiet-window arrangements and an available
recovery operator. Chart hooks and slow startup need the rehearsed deadline.

**Command — CHANGE, explicit maintenance approval required:**

```bash
argocd app sync gitlab
```

Use a full Application sync, not selective resource sync. Do not add force,
replace, or prune flags to work around an unexplained failure.

**Commands — READ-ONLY:**

```bash
argocd app wait gitlab --operation --sync --health --timeout 3600
kubectl --context "$PROD_CONTEXT" -n gitlab get jobs,pods
kubectl --context "$PROD_CONTEXT" -n gitlab logs job/"$MIGRATION_JOB" --all-containers=true
```

**Expected Result:** successful hooks/migrations/rollout within the rehearsed
window. The example timeout is not a promised completion time; preserve logs
before hook cleanup. Multiple replicas do not guarantee zero downtime.
**PASS/FAIL:** failed migration or sustained platform/service failure is FAIL.
**Action if Failed:** stop further actions, preserve evidence and evaluate recovery;
do not repeatedly force-sync or delete migration Jobs.

### 8. Post-upgrade validation

**Purpose:** verify application version, data and operational stability.

**Commands — VALIDATION:**

```bash
kubectl --context "$PROD_CONTEXT" -n gitlab exec deploy/gitlab-toolbox -c toolbox -- \
  gitlab-rake gitlab:env:info
kubectl --context "$PROD_CONTEXT" -n gitlab exec deploy/gitlab-toolbox -c toolbox -- \
  gitlab-rake gitlab:check SANITIZE=true
kubectl --context "$PROD_CONTEXT" -n gitlab exec deploy/gitlab-toolbox -c toolbox -- \
  gitlab-rake gitlab:doctor:secrets
```

Repeat platform and migration checks. Exercise login, SSH/HTTPS clone/push,
pipelines, artifact upload/download, LFS, packages, Registry push/pull and KAS if
used. Functional write tests are **CHANGE** operations in approved test projects.

**Expected Result:** CE 19.2.7/chart 10.2.7; coordinated chart component images;
successful migrations; decryptable secrets; stable DB load/lag, queues, restarts,
errors and storage metrics throughout the agreed observation window.
**PASS/FAIL:** Synced/Healthy alone is insufficient. Keep the final gate open
until required post-deployment and background migrations complete.
**Action if Failed:** keep the maintenance incident open and evaluate recovery.

### 9. Rollback/recovery decision

**Purpose:** avoid an unsafe downgrade after schema/data changes.

**Command — READ-ONLY:** inspect migration state/logs, deployed images, operation
history and backup timestamps. Determine whether any schema/data changes occurred.

**Expected Result:** a documented decision to fix forward or use proven recovery.
**PASS/FAIL:** uncertainty is not permission to downgrade.
**Action if Failed — RECOVERY:** explicitly approve the tested procedure to
restore compatible application, DB, repositories, object data and original
secrets. Account for writes since the backup; control reconciliation during
recovery. Do not improvise `helm rollback`, a chart-pin reversal, or SQL rollback.

### 10. Later 19.3/19.4 upgrade review

**Purpose:** keep minor releases outside the security patch.

**Command — READ-ONLY:** review official version mappings, required stops,
intervening chart/GitLab notes, background migrations and changed restore behavior.
**Expected Result:** separate proposal after this patch is accepted.
**PASS/FAIL:** any 19.3/19.4 change in this PR is out of scope.
**Action if Failed:** split the change and retain this plan's 19.2.7 target.

## Required future repository changes

| File | Future patch adjustment |
| --- | --- |
| `clusters/production/argocd/applications/gitlab.yaml` | `targetRevision: 10.2.6` → `10.2.7` |
| `helm-values/gitlab/VERSION` | `GITLAB_VERSION=19.2.7`, `GITLAB_CHART_VERSION=10.2.7` |
| `scripts/validate.sh` | GitLab render target `10.2.6` → `10.2.7` |

This documentation change does not implement these edits. Preserve CE, manual
sync, runtime identities, storage, networking and external dependencies.
Any decision to change upgradeCheck must be separately explained and rehearsed.

## Exact pre-upgrade checklist

- [ ] Verified production context and reviewed chart/Git revisions recorded.
- [ ] Complete backup: zero access denials and unexplained omissions.
- [ ] Original Rails secrets separately protected and recoverable.
- [ ] External backup copy downloaded and checksum verified.
- [ ] Same-version isolated restore passed.
- [ ] Exact patch rehearsal passed with measured deadlines.
- [ ] CNPG, Redis/Sentinel, MinIO, Gitaly, TLS/VSO, nodes and storage healthy.
- [ ] Measured data/WAL/staging headroom and rollout capacity adequate.
- [ ] Schema and background migrations complete in every configured database.
- [ ] No concurrent backup/restore, prerequisite change, or platform maintenance.
- [ ] Target render, hook/Secret/PVC behavior and full CI reviewed.
- [ ] Recovery owner, acceptable data loss, quiet window and approval recorded.

## Exact post-upgrade checklist

- [ ] Intended workloads use target chart's coordinated images; no old replicas.
- [ ] CE 19.2.7 and chart source 10.2.7 confirmed.
- [ ] Hooks, ordinary and post-deployment migrations succeeded.
- [ ] Background migrations completed before final acceptance.
- [ ] Application checks and secret-decryption checks passed.
- [ ] Git, pipeline, artifact, LFS, package and Registry tests passed.
- [ ] Database lag/load, queues, errors, restarts and storage acceptable.
- [ ] New-version backup captured and verified after stabilization.
- [ ] Evidence and final operator acceptance recorded.

## Final GO / NO-GO criteria and evidence

**NO-GO until all mandatory pre-upgrade gates pass.** Known gaps at document
creation: complete recovery unproven; historical source-access failures not
resolved by repository changes; separate-secret/external-copy evidence absent;
current live health and migrations unknown; target hooks/render and full CI pending.

| Gate | Initial status | Evidence to record |
| --- | --- | --- |
| Recovery Ready | Unproven | Backup manifest, secret custody, external checksum, restore report |
| Platform Healthy | Not freshly verified | Dependency checks, capacity and migration results |
| Rehearsal Passed | Pending | Restore/patch test report and timing |
| Chart Validated | Pending | Reviewed renders/diff, hook behavior, CI run |
| Maintenance Approved | Pending | Operator, reviewer, window, Git SHA and chart |
| Upgrade | Not executed | Sync operation and migration/rollout logs |
| Post-Validation Passed | Pending | Functional tests, metrics and final acceptance |

## Official references

- [Critical patch advisory, including migration impact](https://docs.gitlab.com/releases/patches/patch-release-gitlab-19-4-1-released/)
- [Chart version mappings](https://docs.gitlab.com/charts/installation/version_mappings/)
- [Helm upgrade procedure](https://docs.gitlab.com/charts/installation/upgrade/)
- [Upgrade paths](https://docs.gitlab.com/update/upgrade_paths/)
- [GitLab 19 upgrade notes](https://docs.gitlab.com/update/versions/gitlab_19_changes/)
- [Migration checks](https://docs.gitlab.com/update/background_migrations/)
- [Helm backup and secret custody](https://docs.gitlab.com/charts/backup-restore/backup/)
- [Helm restore procedure](https://docs.gitlab.com/charts/backup-restore/restore/)
- [Argo CD Helm behavior](https://argo-cd.readthedocs.io/en/stable/user-guide/helm/)
- [Argo CD resource hooks](https://argo-cd.readthedocs.io/en/stable/user-guide/resource_hooks/)
- [Kubernetes disruption budgets](https://kubernetes.io/docs/tasks/run-application/configure-pdb/)
- [CNPG 1.30 diagnostics and primary-status warnings](https://cloudnative-pg.io/releases/cloudnative-pg-1-30.0-released/)

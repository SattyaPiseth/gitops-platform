# GitLab 19.2.7 upgrade guide

Upgrade GitLab **Community Edition (CE) 19.2.6 → 19.2.7** with Helm chart
**10.2.6 → 10.2.7**.

**Status: not ready to upgrade (NO-GO).** A complete backup and successful restore
have not been proven. Earlier checks found `403 AccessDenied` errors when the
backup tool read application buckets. Recheck live conditions before proceeding.

This guide describes future work. It does not authorize production changes.
Keep GitLab 19.3/19.4 and changes to PostgreSQL, Redis, MinIO, networking,
credentials, and backup scheduling in separate work.

## Start here

Follow this order. Stop when a required check fails or has no evidence.

**Recovery Ready → Platform Healthy → Rehearsal Passed → Chart Validated →
Maintenance Approved → Upgrade → Post-Validation Passed**

| Step | What you need before continuing |
| --- | --- |
| 1. Prove recovery | Complete backup, separately protected secrets, external copy, successful restore |
| 2. Check platform health | Healthy dependencies, enough storage, completed database migrations |
| 3. Rehearse | Successful patch upgrade in an isolated test environment |
| 4. Prepare the patch | Reviewed version changes, chart differences, and passing CI checks |
| 5. Upgrade production | Explicit approval, maintenance window, and a recovery operator |
| 6. Verify the result | Correct version, working features, completed migrations, and stable monitoring |

**What to do now:** complete step 1. Do not start a production upgrade while the
recovery gate is closed.

## Before using the commands

Run commands from the repository root. Confirm the intended cluster and Argo CD
server before any operation. Replace placeholders with reviewed values.

| Command label | Meaning |
| --- | --- |
| READ-ONLY | Inspect state without deliberately changing configuration or data |
| VALIDATION | Run checks; these may create local reports or use application resources |
| CHANGE | Write data or change a deployment; explicit approval required |
| RECOVERY | Restore or overwrite data; explicit approval required |

Never print credentials, tokens, Secret values, or `.s3cfg` contents. Keep logs,
rendered manifests, and backup evidence in restricted storage outside Git.

## 1. Prove that GitLab can be restored

A backup file alone is not enough. Record evidence for all of these:

- Database and repositories were backed up successfully.
- Every required object-storage bucket was included, with **zero 403 errors**
  and no unexplained skipped components.
- The original Rails encryption secrets are protected separately from the archive.
- A copy outside this cluster was downloaded and its checksum verified.
- That external copy was restored successfully into an isolated environment.

The earlier backup issue remains unresolved by this documentation. Review the
[object-storage configuration](../../platform/gitlab/object-storage/README.md)
and actual MinIO permissions before attempting a new backup. Keep Rails,
Registry, and Toolbox identities separate.

Include Registry, uploads, artifacts, LFS, and packages. Check MR diffs,
Terraform state, and disabled-feature buckets for historical data before
excluding them. A denied request does not mean a bucket is empty or absent.

**READ-ONLY — check access to the required buckets:**

First inspect the available contexts, then set the verified production context:

```bash
kubectl config get-contexts
PROD_CONTEXT='REPLACE_WITH_VERIFIED_PRODUCTION_CONTEXT'
```

```bash
kubectl --context "$PROD_CONTEXT" -n gitlab exec deploy/gitlab-toolbox -c toolbox -- sh -eu -c '
  for bucket in gitlab-registry gitlab-uploads gitlab-artifacts \
    gitlab-lfs gitlab-packages gitlab-backups
  do
    s3cmd --config=/etc/gitlab/.s3cfg --limit=1 ls "s3://$bucket/" >/dev/null
  done
'
```

A successful listing proves only listing access. Also verify that the same
identity can read a representative existing object from each nonempty source.
Do not display object contents.

After a separately approved backup, check its logs and archive metadata, test
nested archive integrity, and compare it with the source inventory. An exit code
of zero or a successful upload does not prove completeness. Empty components
may be skipped only when the inventory explains why.

Use the official [backup procedure](https://docs.gitlab.com/charts/backup-restore/backup/)
and [restore procedure](https://docs.gitlab.com/charts/backup-restore/restore/).
Restore into **CE 19.2.6 / chart 10.2.6** first, using the original Rails secrets,
separate runtime credentials and separate storage. Block access to production
services, email, runners and integrations. Follow the required database-client
shutdown and restart steps. Preserve SSH host keys and document TLS/CA and Vault
recovery too.

**Pass:** all recovery evidence is recorded.

**Fail:** stop and repair the backup or restore process before upgrading.

## 2. Check the platform and database

**READ-ONLY — confirm the baseline and inspect dependencies:**

```bash
cat helm-values/gitlab/VERSION
kubectl --context "$PROD_CONTEXT" -n argocd get applications gitlab gitlab-prerequisites
kubectl --context "$PROD_CONTEXT" get nodes
kubectl --context "$PROD_CONTEXT" -n gitlab get pods,pvc,pdb,jobs
kubectl --context "$PROD_CONTEXT" -n minio-system get pods,pvc
kubectl --context "$PROD_CONTEXT" -n longhorn-system get volumes.longhorn.io
kubectl --context "$PROD_CONTEXT" -n gitlab describe cluster.postgresql.cnpg.io gitlab-postgresql
kubectl --context "$PROD_CONTEXT" -n gitlab exec deploy/gitlab-toolbox -c toolbox -- \
  gitlab-rake db:migrate:status
```

Also open **GitLab Admin → Monitoring → Background migrations**. Confirm no
queued, active, finalizing, or failed migrations remain. Check every configured
GitLab database. Do not force-mark migrations as complete to pass this step.

| Check | Required result |
| --- | --- |
| Version | Deployed CE 19.2.6 and declared chart 10.2.6 agree |
| PostgreSQL | Three healthy instances; replicas streaming without growing lag |
| Redis/Sentinel | Healthy replication, quorum, and primary discovery |
| MinIO and Gitaly | Object and repository access working |
| Storage | Healthy volumes; enough measured data, WAL, and backup staging space |
| Secrets and certificates | VSO synchronization and TLS working |
| Workloads | No unexplained failures or restart increases; sufficient rollout capacity |
| Migrations | Schema and background migrations complete |
| Other work | No concurrent backup, restore, failover, storage rebuild, or platform maintenance |

Running pods and Bound volumes are not sufficient evidence on their own. Use
monitoring to verify replication, capacity, and application behavior.

**Pass:** all checks are healthy and recorded.

**Fail:** stop and resolve the failing dependency separately.

## 3. Rehearse the patch

Use the isolated environment restored in step 1. Apply the proposed chart
10.2.7 change there through the same Argo CD process intended for production.

- Confirm database migrations and chart Jobs complete successfully.
- Run the functional checks in step 6.
- Record migration time, startup time, and recovery time.
- Set the production maintenance window and timeout from those measurements.

**Pass:** restore and patch rehearsal both succeed.

**Fail:** fix the procedure and repeat the rehearsal.

## 4. Prepare and review the repository patch

Update these references together in a future patch PR:

| File | Required change |
| --- | --- |
| [GitLab Application](../../clusters/production/argocd/applications/gitlab.yaml) | Chart `targetRevision` to `10.2.7` |
| [Version record](../../helm-values/gitlab/VERSION) | `GITLAB_VERSION=19.2.7` and `GITLAB_CHART_VERSION=10.2.7` |
| [Validation script](../../scripts/validate.sh) | GitLab chart render target to `10.2.7` |

These are planned edits, not changes made by this guide. Keep CE, manual sync,
storage, credentials, networking, and external dependencies unchanged.

### Review chart differences

On a dedicated validation host or CI, render both charts using the same values
and compare the results. Inspect images, migration Jobs, hooks, permissions,
probes, resources, storage references, ingress, and secret handling. Compare with
Argo CD's desired manifests and API capabilities as well.

**VALIDATION — run the repository checks in the future patch checkout:**

```bash
bash scripts/validate.sh
```

The script requires Docker. Run it in CI or a dedicated Docker-capable host.
**Do not install or enable Docker on the Kubernetes control-plane node.**
Keep rendered manifests private because they can contain sensitive material.

### Review the disabled upgrade check

[GitLab values](../../helm-values/gitlab/values.yaml) currently set
`upgradeCheck.enabled: false`, disabling the chart's upgrade-path check. Do not
silently enable it in the version patch. Document how the upgrade path was
verified and test any proposed hook change separately.

Argo CD maps supported Helm pre-install/pre-upgrade hooks to its PreSync phase.
It does not perform a native Helm upgrade. Review hook ordering, permissions,
recreation, and cleanup in rehearsal. Use a full Application sync: selective
resource sync does not run hooks.

### Account for automatic reconciliation

The main GitLab Application is manual, but the parent Application and
`gitlab-prerequisites` auto-sync. Freeze unrelated changes during the maintenance
window and record the exact values Git commit. Do not assume `main` still points
to the reviewed commit when the operator starts the upgrade.

**Pass:** the diff is understood, hook behavior is proven, and full CI passes.

**Fail:** correct the PR or validation environment before scheduling maintenance.

## 5. Upgrade production after approval

**Stop here until steps 1–4 pass and maintenance is explicitly approved.**
Confirm a fresh verified backup, quiet-window arrangements, the recovery
operator, and the exact chart/Git revision. Multiple application replicas do not
guarantee a zero-downtime upgrade.

**READ-ONLY — verify the Argo CD destination and reviewed changes:**

```bash
argocd app get gitlab
argocd app diff gitlab
```

**CHANGE — perform the approved full sync:**

```bash
argocd app sync gitlab
```

**READ-ONLY — observe progress:**

```bash
argocd app wait gitlab --operation --sync --health --timeout 3600
kubectl --context "$PROD_CONTEXT" -n gitlab get jobs,pods
```

The one-hour timeout is an example; use the rehearsed deadline. Inspect the
current migration Job logs and preserve them before hook cleanup.

**Pass:** migrations, hooks, and rollout complete within the approved window.

**Fail:** stop further actions and follow the failure procedure below. Do not
force-sync repeatedly or delete migration Jobs to hide a failure.

## 6. Verify the upgraded service

**VALIDATION — check version, application health, and secret decryption:**

```bash
kubectl --context "$PROD_CONTEXT" -n gitlab exec deploy/gitlab-toolbox -c toolbox -- \
  gitlab-rake gitlab:env:info
kubectl --context "$PROD_CONTEXT" -n gitlab exec deploy/gitlab-toolbox -c toolbox -- \
  gitlab-rake gitlab:check SANITIZE=true
kubectl --context "$PROD_CONTEXT" -n gitlab exec deploy/gitlab-toolbox -c toolbox -- \
  gitlab-rake gitlab:doctor:secrets
```

Confirm CE **19.2.7**, chart **10.2.7**, and the target chart's coordinated images.
Repeat platform and migration checks from step 2. Check login, SSH/HTTPS Git
operations, pipelines, artifacts, LFS, packages, Registry, and KAS if used.
Tests that push data or run pipelines are **CHANGE** operations: use approved
test projects.

Observe database load/lag, queues, restarts, errors, and storage for the agreed
period. Capture and verify a new-version backup after stabilization.

**Pass:** all tests pass and required post-deployment/background migrations finish.

**Fail:** keep the incident open. `Synced/Healthy` alone is not final acceptance.

## If the upgrade fails

1. **READ-ONLY:** preserve logs and establish which migrations and changes ran.
2. Stop further upgrade actions and involve the recovery operator.
3. Decide whether to fix forward or use the tested recovery procedure.
4. **RECOVERY:** restore only with explicit approval, matching application/data
   versions and original secrets. Account for data written since the backup and
   control Argo CD reconciliation during recovery.

**Do not assume changing the chart back to 10.2.6 safely reverses database
migrations.** Do not improvise a Helm rollback or SQL rollback.

## Record the decision

For each row, record the operator, time, PASS/FAIL and a restricted evidence link.
Missing evidence means the gate is still closed.

| Gate | Evidence required | Result |
| --- | --- | --- |
| Recovery ready | Complete backup, separate secrets, external checksum, restore report | Pending |
| Platform healthy | Dependency, storage and migration checks | Pending |
| Rehearsal passed | Successful restore/patch tests and measured timings | Pending |
| Chart validated | Reviewed diff, hook behavior and full CI result | Pending |
| Maintenance approved | Approver, window, recovery operator, chart and Git revision | Pending |
| Upgrade completed | Sync, migration and rollout results | Pending |
| Post-validation passed | Functional tests, stable metrics, new backup and acceptance | Pending |

**GO:** all pre-upgrade gates pass and maintenance is approved.

**NO-GO:** any recovery, database, storage, migration, or platform check fails or
remains unverified. Close the upgrade only after post-validation passes.

Review GitLab 19.3/19.4 in a separate plan after this patch is accepted.

## References

- [Patch advisory and migration impact](https://docs.gitlab.com/releases/patches/patch-release-gitlab-19-4-1-released/)
- [Chart version mappings](https://docs.gitlab.com/charts/installation/version_mappings/) and [upgrade paths](https://docs.gitlab.com/update/upgrade_paths/)
- [Helm upgrade procedure](https://docs.gitlab.com/charts/installation/upgrade/) and [migration checks](https://docs.gitlab.com/update/background_migrations/)
- [Backup and secret protection](https://docs.gitlab.com/charts/backup-restore/backup/) and [restore procedure](https://docs.gitlab.com/charts/backup-restore/restore/)
- [Argo CD Helm behavior](https://argo-cd.readthedocs.io/en/stable/user-guide/helm/) and [resource hooks](https://argo-cd.readthedocs.io/en/stable/user-guide/resource_hooks/)
- [Kubernetes disruption budgets](https://kubernetes.io/docs/tasks/run-application/configure-pdb/) and [CNPG diagnostics](https://cloudnative-pg.io/releases/cloudnative-pg-1-30.0-released/)
- [Existing GitLab validation guide](deployment-validation-guide.md)

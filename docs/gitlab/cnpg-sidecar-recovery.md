# CNPG missing-sidecar recovery proposal

Status: proposed only. Do not apply without approval for the temporary primary
update policy and the database interruption.

## Diagnosis

CNPG 1.30.0 pauses supervised updates before calling updatePrimaryPod. That
function contains the missing-WAL-sidecar recreation fix, but the supervised
pause prevents it running. Manual promotion stalled; it was cancelled by
returning targetPrimary to the existing primary, gitlab-postgresql-2.
The write endpoint returned and GitLab readiness was HTTP 200.

The primary-specific kubectl cnpg restart requests an in-place PostgreSQL
restart. It does not replace the Pod and cannot inject the sidecar.

## Proposed temporary GitOps change

In platform/gitlab/database/cluster.yaml only:

```yaml
spec:
  primaryUpdateStrategy: unsupervised
  primaryUpdateMethod: restart
```

This allows the operator's rollout path to recreate the primary when its Pod
spec must change, rather than attempting another switchover. It temporarily
removes the manual primary-update gate. It must not become the standing policy.
Argo automatically reconciles this application: merging begins the operation.

## Execution gate

- Recheck currentPrimary and targetPrimary both identify the existing primary.
- Verify both replicas stream without lag, all storage is healthy, and sufficient
  CPU/memory requests remain for the sidecar.
- Confirm no unrelated database spec or operator change is pending.
- Confirm current application backup availability and acknowledge that restore
  testing is deferred; this procedure is not a proven recovery drill.
- Approve the maintenance interruption and prepare the restoration commit first.

## Observe and restore settings

1. Observe CNPG recreate the existing primary Pod using its retained data/WAL
   PVCs. Do not manually remove PVCs or bypass leases.
2. Confirm the new Pod UID and ready Barman sidecar, a ready write endpoint,
   one writable primary, healthy streaming replicas, and application readiness.
3. Verify new WAL archival success and fresh archive objects; old counters or
   conditions alone are insufficient.
4. Restore primaryUpdateStrategy: supervised and primaryUpdateMethod: switchover
   through GitOps promptly after stabilization.
5. Request a manual base backup only as a separate observed step.

Stop on unexpected primary identity, replication loss, pending storage, or
sidecar failures. Do not stack forced promotions or remove archive data.
If pod recreation fails, restoring the policy alone will not restore service;
inspect the failure and preserve all PVCs and database data.

## Sources

- [CNPG 1.30.0 rollout implementation](https://github.com/cloudnative-pg/cloudnative-pg/blob/v1.30.0/internal/controller/cluster_upgrade.go)
- [Upstream missing-sidecar fix](https://github.com/cloudnative-pg/cloudnative-pg/pull/11032)
- [Primary restart implementation](https://github.com/cloudnative-pg/cloudnative-pg/blob/v1.30.0/internal/cmd/plugin/restart/restart.go)

# CNPG backup activation

Status: prepared locally; not deployed. Recovery testing remains deferred.

## Before merging

Merging activates WAL archival through automated gitlab-prerequisites sync.
Observe this change during a database maintenance window. A sidecar rollout
can replace database pods and a supervised primary update may need operator
intervention. Do not switch to unsupervised updates simply to finish the rollout.

- Recheck all three instances Ready and both replicas streaming without lag.
- Recheck worker requests: the preparation snapshot reached 94% memory and
  93% CPU requests on different workers. The proposed sidecar adds 100m CPU
  and 128 MiB memory requests to each instance, with a 512 MiB memory limit.
  These are initial settings, not a proven peak-memory budget.
- Confirm Longhorn volumes healthy, sufficient data/WAL free space, and no
  competing maintenance, backup, or restore.
- Verify a current application backup and external archive are available.
- Prerequisite PR #14 is deployed; VSO and ObjectStore exist. Toolbox tests
  passed TLS, prefix listing, upload/readback, multipart completion and abort.
  Those tests do not prove database-side Barman operation.
- Administrator reports the two validation objects removed. Do not reuse a
  prefix containing an unrelated PostgreSQL archive.

## Observe activation

1. Watch the Cluster conditions, pod readiness, scheduling events, and plugin
   containers. Stop progressing if a replica cannot become Ready.
2. If CNPG requests a supervised primary update, check the current primary,
   candidate health and lag before approving a switchover. Expect connections
   to reconnect. Never promote a guessed pod name from an old snapshot.
3. Verify Barman WAL uploads and current successful archive activity. An old
   ContinuousArchiving=True condition is insufficient evidence: it existed
   before the plugin was configured.
4. After all instances are healthy, request one manual plugin base backup in
   a separate observed step. Require completed Backup status and verify the
   archive objects. No Backup or ScheduledBackup is part of this change.
5. Monitor WAL growth, archive failures, resource consumption and all seven
   monitoring targets. Record any required resource adjustment.

## Stop or rollback

Do not delete archive objects or credentials. On scheduling or archive errors,
inspect the exact failure before making another database change. Removing the
plugin stops future archive coverage and may itself require another rollout;
a Git revert is not a data restore. Preserve existing WAL/base backups and
coordinate rollback while maintaining a healthy primary and replicas.

A base backup and WAL archive do not prove PITR until restored. They also do
not replace GitLab repository/object-storage and encryption-secret backups.

[Official plugin procedure](https://cloudnative-pg.io/plugin-barman-cloud/docs/usage/)

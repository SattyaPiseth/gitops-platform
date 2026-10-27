# GitLab isolated restore checklist

Status: recovery gate closed. The isolated restore drill is deferred by the owner because test capacity is unavailable; it has not passed. A verified external archive copy exists; an isolated restore and encrypted recovery-secret copy are still pending. Automated backups remain disabled.

## Verified archive

- Backup ID: `1790506879_2026_09_27_19.2.7` (GitLab CE 19.2.7).
- Archive size: 2,754,560 bytes.
- SHA-256: `964aae43a56d53f1dc8ccc456101ad11f67814b6432dda7bce77f80d398737f0`.
- Local evidence: `/home/sysadmin/.local/share/gitlab-recovery/1790506879_2026_09_27_19.2.7/`.
- External archive: `manager@172.16.6.5:/opt/backups/gitlab/1790506879_2026_09_27_19.2.7_gitlab_backup.tar`.
- Both archive checksums were rechecked during the recovery-stage review and match. External file permissions are `0600`.
- Saved verification records document archive checks and explain the builds omission: the database dump contains no CI build, job-artifact, or trace rows. These are historical snapshot findings, not a new production backup.
- Neither archive inspection nor checksum matching proves successful application recovery.

## Remaining inputs

1. Select an isolated test cluster, owner, and restore window. No test target is confirmed.
2. Supply an approved encryption recipient/public key for the separate recovery-secret copy. Never put private keys or secret values in Git.
3. Confirm whether the external host uses a different physical host/datastore from production. An external VM alone does not prove independent storage.
4. Obtain sanitized administrator confirmation that the previously exposed MinIO root credential was rotated. Do not use that credential for verification.
5. Recheck the live seven-source-bucket backup policy before another backup; prior five-bucket evidence does not establish the newer scope.

## Prepare a separate test environment

- Select an isolated test cluster, capacity, owner and maintenance window. Do not install Docker on the management/control-plane node.
- Use GitLab CE 19.2.7 and chart 10.2.7 for this archive.
- Use separate PostgreSQL, Redis, Gitaly volumes and object-storage buckets. Restore credentials must have access only to test targets.
- Use a test hostname and restrict access. Block outbound email, webhooks, production integrations and runner execution before starting restored workloads.
- Do not attach production Vault paths or allow test reconciliation to overwrite production secrets. Transfer recovery material through an approved protected channel.
- Check the Kubernetes context and every database/storage endpoint before approving any restore command. A different namespace alone is insufficient isolation.

## Execute only after target approval

1. Verify the transferred archive checksum and available working disk space.
2. Restore the matching Rails secrets securely, stop test database clients, and run the chart restore utility against test resources only.
3. Bring test services back up and capture sanitized logs and timings.

This follows the [official Helm restore procedure](https://docs.gitlab.com/charts/backup-restore/restore/). Exact commands will be filled in after the target is selected; no production-context restore commands are provided here.

## Pass criteria

- Database and repository restore completes without unexplained errors.
- An authorized test account can sign in and access expected projects.
- Git clone and wiki access work; restored commit identifiers match recorded expectations.
- Known uploads download successfully and match expected content/checksums.
- Encrypted application data can be read with the restored secrets.
- Required object components are restored or have documented empty-input evidence.
- No production endpoints were written and no external jobs/messages were triggered.
- Record duration, failures, remediation and reviewer approval. Keep sensitive logs outside Git.

## Separate external-copy gate

The archive copy above passes checksum verification. Confirm its independent failure domain and retention, then transfer and verify separately encrypted recovery material. Never copy plaintext Rails secrets to the external host. A successful local drill does not satisfy this external-copy gate.

Scheduling stays disabled until backup completeness, external copy and the restore drill are accepted. See [policy review](backup-policy-review.md).

## Prepared schedule (disabled)

`helm-values/gitlab/values-production.yaml` prepares a daily 02:00 Asia/Phnom_Penh run with both `enabled: false` and `suspend: true`. The time is a proposal, not an approved recovery-point objective. Enabling the CronJob alone leaves it suspended.

`Forbid` prevents overlap between jobs of this CronJob, but does not block manual Toolbox backups. Automatic retries are disabled so failures require review. Job history limits retain Kubernetes job records, not backup archives. No archive-deletion permission or retention pruning is added.

Before activation, confirm the schedule, working-storage capacity, time limit based on measured backup duration, network-policy selection for CronJob pods, and resource requests in a rehearsal. The values now propose a 10 GiB Longhorn RWO scratch volume with persistence enabled, while the CronJob remains disabled. Validate the rendered PVC behavior and size scratch storage from source data plus archive size, not the current compressed sample alone.

The chart invokes backup-utility directly: it can report success after a component access check was skipped. A failure-detection mechanism for 403s, unexpected skips, missing archives and stale backups must be implemented and rehearsed before activation. Do not equate a successful Job with an accepted backup.

After all gates pass, a separate reviewed change must enable the CronJob and remove suspension. Do not merge activation with recovery experiments.

# GitLab isolated restore checklist

Status: preparation only. No restore environment or external backup destination is available. Automated backups remain disabled under the agreed recovery gate.

## Evidence already collected

- Backup ID: `1790447325_2026_09_26_19.2.7`
- Archive size: 2,754,560 bytes.
- SHA-256: `3dcc5903c4921195818a0bd6be2c6b8cd6a00ced5b7bb590c0bb90afa96b4fce`
- Local archive structure and compressed database/uploads passed inspection. Repository files are present; repository integrity and application restore remain untested.
- Archive permissions were changed to `0600`. Recovery secrets were already `0600`; their contents were not read.
- The management-node copy is staging, not an independently protected offsite backup.
- No full backup log was found among the files listed in the provided Antigravity handoff directory. The browser scratchpad has not been inspected for embedded logs.

## Resolve incomplete evidence

Backup metadata also marks builds, registry, artifacts, LFS and packages skipped. Earlier administrator reports show the four object buckets empty, but they do not prove the state at backup time. Determine why builds was skipped and corroborate all skips from the original log. If that log cannot be recovered, plan an approved fresh backup with securely captured logs; do not label the existing archive complete from its exit status or structure alone.

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

Provision an independently administered destination outside this cluster, with protected credentials and agreed retention. Copy and checksum-verify both the archive and separately encrypted recovery material. A successful local drill does not satisfy this external-copy gate.

Scheduling stays disabled until backup completeness, external copy and the restore drill are accepted. See [policy review](backup-policy-review.md).

## Prepared schedule (disabled)

`helm-values/gitlab/values-production.yaml` prepares a daily 02:00 Asia/Phnom_Penh run with both `enabled: false` and `suspend: true`. The time is a proposal, not an approved recovery-point objective. Enabling the CronJob alone leaves it suspended.

`Forbid` prevents overlap between jobs of this CronJob, but does not block manual Toolbox backups. Automatic retries are disabled so failures require review. Job history limits retain Kubernetes job records, not backup archives. No archive-deletion permission or retention pruning is added.

Before activation, confirm the schedule, working-storage capacity, time limit based on measured backup duration, network-policy selection for CronJob pods, and resource requests in a rehearsal. The preparation leaves persistence disabled and creates no PVC. Determine whether dedicated scratch storage is needed from source data plus archive size, not the current compressed sample alone.

The chart invokes backup-utility directly: it can report success after a component access check was skipped. A failure-detection mechanism for 403s, unexpected skips, missing archives and stale backups must be implemented and rehearsed before activation. Do not equate a successful Job with an accepted backup.

After all gates pass, a separate reviewed change must enable the CronJob and remove suspension. Do not merge activation with recovery experiments.

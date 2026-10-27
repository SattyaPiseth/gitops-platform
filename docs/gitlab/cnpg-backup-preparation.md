# GitLab PostgreSQL backup preparation

Status: historical preparation and validation notes. The current repository
declares the credential synchronization, ObjectStore, and Cluster plugin that
enables WAL archival. That desired state does not prove a live reconciliation,
successful archive, base backup, or recovery. No backup schedule is declared;
the isolated restore drill remains deferred and recovery unproven.

## Verified baseline — 2026-09-28

- CNPG chart 0.29.1 (app 1.30.1); Barman plugin chart 0.7.1.
- The GitLab Cluster declares the Barman plugin as its WAL archiver.
- A VaultStaticSecret declares the dedicated CNPG object-storage credential in
  `gitlab`; check its live `SecretSynced` condition rather than assuming it
  exists or contains valid credentials.
- `cnpg-backups` is declared in the MinIO values; live contents and IAM scope
  must be checked by the administrator.
- Monitoring fix PR #13 is deployed. All three PostgreSQL, three Redis, and
  one Gitaly target report UP with no scrape errors.

## Declared dedicated configuration

| Item | Proposed value |
| --- | --- |
| MinIO identity | `gitlab-cnpg-backup` |
| Vault KV v2 path | `kv/gitlab/postgresql-backup` |
| Kubernetes Secret | `gitlab-postgresql-backup` |
| Secret keys | `accessKeyId`, `secretAccessKey` |
| ObjectStore | `gitlab-postgresql-backups` |
| Backup location | `s3://cnpg-backups/gitlab-production/` |
| S3 endpoint | `https://minio.minio-system.svc.cluster.local` |

Keep this identity separate from Rails, Registry, and Toolbox. No secret values
belong in Git, terminal output, or chat. Check whether an equivalent identity
already exists before creating one.

## Execution order

1. Administrator confirms the bucket exists, the proposed prefix has no
   conflicting archive, and reports current encryption, lifecycle, and capacity.
2. Review an exact-prefix IAM policy for list, read, upload, and multipart
   operations. Initially omit deletion and automated retention. Review Barman
   permissions against the installed version and test them before activation.
3. Store the dedicated credential in Vault. Give the VSO role read access only
   to the required path and synchronize the two keys to the declared Secret.
4. Confirm the MinIO CA trust source and hostname verification. Confirm the
   ObjectStore is Ready only after credentials and trust references are ready.
5. Review Cluster plugin changes. Adding or changing a sidecar can require
   database pod replacement: check resource headroom, replication, disruption
   budgets, and the supervised primary-update procedure first.
6. Verify WAL archival, then request one manual base backup. Record Backup
   status, object presence, sizes, and errors; alert on failed archival and WAL
   filesystem growth. Do not regard uploaded files as proof of PITR recovery.
7. Establish an independent external copy and later perform isolated PITR.
   Scheduling and retention require a separate decision; the restore test is
   currently deferred, not passed.

Use the existing narrowly allowed MinIO network path if live tests confirm it.
Do not widen default-deny or reuse the Toolbox credential.

## Cluster fragment — declared in Git

```yaml
spec:
  plugins:
    - name: barman-cloud.cloudnative-pg.io
      isWALArchiver: true
      parameters:
        barmanObjectName: gitlab-postgresql-backups
```

The active platform manifest includes this fragment. Verify the Secret and
ObjectStore in the live cluster before relying on it. The historical example
files below remain outside Argo discovery paths.

## Acceptance and recovery limits

A base backup plus its required WAL chain enables database recovery only.
GitLab also needs matching repositories, object data, and Rails encryption
secrets. PostgreSQL PITR does not coordinate those components automatically.
Do not manually delete WAL objects or add expiration independently of Barman's
recovery chain. A future retention policy must retain a recoverable base backup
and all required WAL, with deletion scoped to this dedicated prefix.

## References

- [Barman plugin usage](https://cloudnative-pg.io/plugin-barman-cloud/docs/usage/)
- [Recovery checklist](isolated-restore-checklist.md)

Online Barman documentation currently describes 0.15.0. The installed deployment
is 0.14.0; validate final manifests against its installed CRDs and version-specific
behavior before rollout.

## Prepared drafts — not deployed

Historical administrator report: the MinIO identity and Vault path did not
exist; `cnpg-backups` existed and `gitlab-production/` was absent.

- [MinIO IAM policy](../../policies/minio/gitlab-cnpg-backup.draft.json)
- [Vault policy addition](examples/cnpg-backup/vault-policy.hcl)
- [VSO credential synchronization](examples/cnpg-backup/vault-static-secret.yaml)
- [Barman ObjectStore](examples/cnpg-backup/objectstore.yaml)

These historical examples are outside Argo discovery paths. The active platform
manifests now declare the Cluster plugin, but no Backup or ScheduledBackup is
added by these examples.

The IAM policy permits bucket-location lookup and bucket-level listing,
plus object reads, writes, and per-upload multipart operations only beneath
`gitlab-production/`. Bucket-wide multipart-upload enumeration is omitted;
ordinary multipart upload does not require it. Verify installed Barman behavior
before granting anything further. Barman HeadBucket requires bucket-level ListBucket; root-level listing is consequently allowed. Object reads and writes remain prefix-scoped.
No deletes, lifecycle changes, bucket creation, or administrative actions are
included. PutObject still permits overwrite: this is not immutable storage.

The ObjectStore proposes `gitlab-tls` / `ca.crt`, matching the existing GitLab
custom CA reference. Its ability to validate the MinIO endpoint must be tested
before deployment; do not disable TLS verification. Encryption-at-rest remains
an administrative check, not something established by this draft.

After administrative approval, create only the dedicated MinIO user and policy,
store its credential fields privately in Vault, and add the exact Vault read
path to the existing role's policy. Do not expose values in chat or shell
arguments. Validate effective IAM permissions including inherited grants.
Then promote VSO and ObjectStore through a focused GitOps change. Validate
Secret synchronization, TLS, prefix access, and expected outside-prefix denial
before proposing the database rollout. Server dry-run validates API shape only,
not credentials, IAM enforcement, or TLS connectivity.

Do not configure retention while the identity lacks deletion permission. Do not
rotate Rails, Registry, or Toolbox credentials as part of this preparation.

## Fresh-installation baseline and HeadBucket correction

The owner confirmed keeping the reinstalled GitLab. Earlier archive checks do
not establish backup coverage for this new installation. No old data restore
is planned in this procedure.

Live Barman failed HeadBucket with HTTP 403. The earlier prefix-conditioned
ListBucket grant did not cover that call; Toolbox prefix tests missed it.
The corrected local policy grants ListBucket on cnpg-backups without a prefix
condition. This permits enumeration of object names throughout that bucket,
including outside gitlab-production/, but does not permit reading or writing
those other objects. GetObject, PutObject and multipart object permissions
remain limited to cnpg-backups/gitlab-production/*. Deletion and administration
remain ungranted. This metadata visibility is a deliberate compatibility tradeoff.
If the bucket is shared and that visibility is unacceptable, use a dedicated
bucket instead of applying this correction.

Administrator action: replace only the dedicated gitlab-cnpg-backup IAM policy
with the corrected JSON. Do not rotate credentials or alter application policies.
After confirmation, verify HeadBucket and fresh WAL archival, then prepare a
manual base backup for the fresh installation. Do not start a base backup until
archival is working. Live effective permissions still require verification.

[HeadBucket permissions](https://docs.aws.amazon.com/AmazonS3/latest/API/API_HeadBucket.html)

# GitLab backup policy review

Status: draft only. Permission structure reviewed; bucket coverage and effective access remain unverified. Recovery readiness is not proven.

## Version baseline

Reviewed on 2026-09-26 against repository chart `10.2.7`, version record `19.2.7`, deployed Toolbox CE image `v19.2.7`, and MinIO image `RELEASE.2025-04-08T15-41-24Z`. The earlier 19.2.6 baseline is superseded. Restore tests must use the exact GitLab version and edition recorded in the selected backup.

Official online documentation changes over time. Installed backup source was inspected to resolve version-specific behavior. Current MinIO AIStor documentation is used for common S3 policy semantics, not as proof that this older MinIO release supports every current AIStor feature. JSON syntax checks are not a MinIO authorization test.

## Proposed change

The [draft MinIO policy](../../policies/minio/gitlab-toolbox-backup.draft.json) gives the dedicated Toolbox identity read access to five named source buckets and upload/read access to `gitlab-backups`. It includes multipart upload support, but no object deletion, source writes, bucket creation, account-wide bucket listing, or administrative actions.

Rails and Registry keep their separate credentials. No networking changes are proposed.

This is not a final policy or a complete-backup guarantee. The policy grants archive uploads, which can overwrite an existing key; independent versioning/immutability and external copies still require review. Other attached policies can grant additional privileges. Removing a grant from this document does not revoke a grant inherited elsewhere.

## Permission review

| Purpose | Actions | Scope and reasoning |
| --- | --- | --- |
| Enumerate source objects | `s3:ListBucket` | Exact source bucket ARNs; not account-wide bucket discovery |
| Resolve bucket location | `s3:GetBucketLocation` | Exact buckets; client compatibility permission |
| Download source data | `s3:GetObject` | Objects inside named source buckets only |
| Inspect archives | `s3:ListBucket`, `s3:GetObject` | `gitlab-backups` only; supports verification and download |
| Upload archives | `s3:PutObject` | `gitlab-backups/*`; also authorizes initiating, uploading and completing multipart uploads |
| Resume/inspect multipart uploads | `s3:ListBucketMultipartUploads`, `s3:ListMultipartUploadParts` | Backup bucket only; support installed s3cmd multipart inspection/resume paths, not required for every fresh upload |
| Cancel incomplete uploads | `s3:AbortMultipartUpload` | Backup objects only; does not grant deletion of completed archives |

Bucket actions use bucket ARNs; object actions use object ARNs. The `/*` suffix covers object keys inside an explicitly named bucket; it is not a wildcard action or an all-buckets grant. No `s3:*`, `ListAllMyBuckets`, ACL changes, policy administration, source writes, object deletion or version deletion are granted.

The `2012-10-17` policy Version is the policy-language identifier, not the GitLab or MinIO release date. The JSON is an identity policy, not a public bucket policy.

## Boundaries and limitations

- The installed utility downloads current visible objects. It does not preserve all historical object versions or delete markers. Historical recovery needs a separately verified version-aware copy; simply adding `GetObjectVersion` would not make this utility version-aware.
- The draft is a narrow Allow policy, not a permission boundary. Direct/group grants, bucket policies, parent identity permissions, service-account restrictions and explicit denies must all be reviewed. Do not add a standing source-write Deny that would unintentionally block the separately approved restore identity/add-on.
- No encryption-key permissions are assumed. Verify actual encryption mode and read access using this MinIO deployment; do not copy AWS KMS permissions blindly into MinIO policies.
- The whole backup bucket is scoped because the current utility writes at its root. A prefix restriction would require matching backup/restore configuration and testing first.
- Backup data contains sensitive application information. TLS verification, Vault/VSO credential management, independently protected recovery secrets and an external recovery copy remain requirements. This IAM policy alone provides neither immutability nor protection from overwrite.

## Evidence required before applying

1. MinIO administrator: supply sanitized policy JSON for direct attachments, groups and service-account restrictions. Include conditions and explicit denies. Confirm the restore policy is detached.
2. Inspect current and historical/versioned objects in `gitlab-mr-diffs` and `gitlab-terraform-state`. Administrator reports both empty and un-versioned; live configuration disables both. Their grants have now been removed from the draft.
3. Check enabled features and historical data for Pages, CI secure files, agent plan content and dependency proxy. Add only the required exact bucket names after reviewing the installed backup utility behavior. Recheck this scope whenever features are enabled.
4. Keep `gitlab-backup-tmp` permissions out of the standing policy: installed code uses it for the restore safety copy, not normal backup.
5. Vault administrator: confirm `kv/gitlab/object-storage/backup` metadata and the presence of `config`, without exposing its value.

## Verified installed utility behavior

Read-only inspection of `/usr/local/bin/backup-utility` and `/usr/lib/ruby/vendor_ruby/object_storage_backup.rb` confirmed:

- Normal S3 backup lists source buckets and downloads objects to Toolbox before creating archives. Its sync deletion flag applies to the local destination, not the source bucket.
- A failed bucket-existence/access check prints a warning and returns without aborting the overall backup. Reject logs containing `Unable to check existence of bucket` or unexplained `Skipping backup`, even when the process exits successfully.
- The utility attempts registry, uploads, artifacts, LFS, packages, external diffs, Terraform state, Pages, CI secure files and agent plan content. This fixed list does not prove every feature is enabled.
- Runtime bucket mappings include `gitlab-pages`, `gitlab-ci-secure-files` and `gitlab-agent-plan-content`. Live configuration now confirms these features disabled; administrator bucket listing does not show these buckets. Explicit skips are proposed below.
- Dependency proxy is absent from the utility component list. If its data requires recovery, define separate coverage instead of assuming it is inside the GitLab archive.
- `gitlab-backup-tmp` is used by restore to copy existing source objects before deleting and replacing them. It is not used by the inspected normal backup path.
- Archive deletion is conditional on `MAXIMUM_BACKUPS`, which is currently unset in Toolbox. Keep it unset for the no-delete standing policy; use separately approved retention management.

These findings justify retaining the draft's source-read-only scope, omitting temporary-bucket access, and omitting archive deletion. They do not prove effective MinIO permissions or backup completeness.

## Proposed credential refresh

After explicit approval, apply only the reviewed standing policy and keep restore permissions detached. Rotate only the dedicated Toolbox credential through Vault/VSO. Never put credentials in Git or command output.

The Toolbox copies projected Secret data during initialization. Propose adding this field under the backup VaultStaticSecret `spec` before rotation:

```yaml
rolloutRestartTargets:
  - kind: Deployment
    name: gitlab-toolbox
```

The restart target is prepared in the local VSO manifest only; it is not deployed. Before deploying the restart target, confirm no backup or restore is running. Verify synchronization and the refreshed Toolbox configuration without displaying credentials; revoke the old credential after successful validation.

## Acceptance gate

- List and read representative objects from every required source bucket using the Toolbox identity. Listing alone does not prove object-read permission.
- Confirm historical bucket coverage with administrative evidence.
- Run a manual backup only after approval; require successful DB, repository and object-storage stages, zero AccessDenied errors and no unexplained skips.
- Inspect archive contents and metadata; preserve GitLab recovery secrets separately in protected storage.
- Copy the verified backup outside the cluster and verify its checksum.
- Restore in an isolated environment using the exact version and edition that created the backup. Record functional checks and recovery time.
- Schedule backups and retention only after recovery is proven.

An uploaded archive or exit code zero alone is not acceptance.

## References

- [GitLab external object storage](https://docs.gitlab.com/charts/advanced/external-object-storage/)
- [GitLab Helm backup and restore](https://docs.gitlab.com/charts/backup-restore/)

- [MinIO policy action reference](https://docs.min.io/aistor/administration/iam/access/)
- [S3 multipart operations and permissions](https://docs.aws.amazon.com/AmazonS3/latest/userguide/mpuoverview.html)

## Reviewed evidence and proposed rollout

Toolbox `host_base` and the administrator's `prod` alias both identify `minio.minio-system.svc.cluster.local`. HTTPS is enabled. Do not copy the administrator's `--insecure` option into backup configuration.

Administrator reports: user `gitlab-backup` has only policy `gitlab-backup`, no groups and no child access keys. Existing policy grants writes/deletes only to the archive and temporary buckets. All inspected buckets report private/un-versioned; only uploads contains current objects (3 objects, 146 KiB). The backup bucket is empty. These are administrator-reported observations, not an independently exported complete bucket-policy audit.

Live generated GitLab configuration confirms Pages, CI secure files, agent plan content, external diffs, Terraform state and dependency proxy disabled. Artifacts, uploads, LFS and packages are enabled. Registry remains in backup scope. Recheck feature settings and bucket contents immediately before execution; investigate any unexpected state.

Policy replacement and VSO preparation approved by the user; production application remains pending. Credential rotation and backup execution require their subsequent gates.

1. The administrator confirms IAM policy `gitlab-backup` is attached only to user `gitlab-backup`. Using separately authenticated administrative access, replace its contents with the reviewed draft. Do not merely add grants while leaving archive-delete permissions attached. Keep restore grants detached.
2. Review and deploy the local backup VSO restart target through GitOps. Confirm no backup/restore is active before sync or rotation.
3. Rotate only the dedicated backup user's credential through approved MinIO/Vault administration. Preserve the existing S3 configuration fields and update only the intended credential fields in Vault. Confirm VSO synchronization and Toolbox restart without showing Secret values. Coordinate replacement and validation so an old credential is not revoked prematurely where overlapping credentials are supported.
4. Verify source listing plus actual GET of the known upload objects, verify archive upload/download with a unique validation key, and arrange deletion of the test key through a separate administrator. The standing identity must not acquire delete permission for test cleanup.
5. After approval and successful access tests, use the following reviewed component selection for a new manual backup:

```sh
kubectl exec -n gitlab deploy/gitlab-toolbox -c toolbox -- \
  backup-utility --skip external_diffs --skip terraform_state \
  --skip pages --skip ci_secure_files --skip agent_plan_content
```

These five intentional skips must be recorded alongside the feature and inventory evidence. Any additional skipped component, failed bucket check or 403 fails acceptance. An empty required bucket may produce no component tar; distinguish verified empty input from access failure.

6. Verify DB/repository stages, archive content and metadata, separately protected recovery secrets, an external verified copy, and an isolated same-version CE restore before declaring readiness.

The previously disclosed administrative credential must be handled through a separate authorized root-credential incident/rotation procedure. Do not use it for these steps or store it in this repository. It is distinct from dedicated backup-user rotation.

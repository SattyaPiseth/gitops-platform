# GitLab Object Storage Architecture & Connection Readiness

> **Environment:** Production (`k8s.tss.local`)  
> **Target Services:** GitLab Rails/Workhorse/Sidekiq, Container Registry, Toolbox Backup  
> **Status:** Production Connection Baseline  

---

## 1. Core Principle: 3 Distinct Storage Groups

GitLab does not use one identical S3 configuration or credential set for every component. We intentionally separate storage into **three distinct security groups**:

```text
                           Object Storage Groups
                                     │
     ┌───────────────────────────────┼───────────────────────────────┐
     │                               │                               │
     ▼                               ▼                               ▼
[1. Rails Object Storage]   [2. Registry Storage]         [3. Backup Storage]
 • Artifacts, LFS, Uploads   • OCI Image Blobs & Manifests • Full System Backups (.tar)
 • Packages, MR Diffs        • Key: config                 • Staging Temp Bucket
 • Key: connection           • Secret:                     • Key: config
 • Secret:                     gitlab-registry-storage     • Secret:
   gitlab-object-storage                                     gitlab-backup-object-storage
```

This segregation enforces **least-privilege access**:
* The **Registry credential** has access ONLY to `gitlab-registry`.
* The **Backup credential** has access ONLY to `gitlab-backups` and `gitlab-backup-tmp`.
* The **Rails credential** has access to the standard application buckets (`gitlab-artifacts`, `gitlab-lfs`, etc.).

---

## 2. Group 1: Rails Consolidated Object Storage (`gitlab-object-storage`)

Consolidated object storage configuration for Rails, Workhorse, and Sidekiq.

### Kubernetes Secret Specification
* **Secret Name:** `gitlab-object-storage`
* **Secret Key:** `connection`
* **Format:** YAML (Fog S3 format)
* **Vault Source Path:** `kv/data/gitlab/object-storage/rails`

### Connection Configuration Format (`connection`)
```yaml
provider: AWS
region: us-east-1
aws_access_key_id: "<RAILS_S3_ACCESS_KEY>"
aws_secret_access_key: "<RAILS_S3_SECRET_KEY>"
host: s3.k8s.tss.local
endpoint: https://s3.k8s.tss.local
path_style: true
aws_signature_version: 4
```

> **Note on MinIO / Ceph:** `path_style: true` and `aws_signature_version: 4` are required for S3-compatible backends like MinIO or Ceph Object Gateway.

---

## 3. Group 2: Container Registry Storage (`gitlab-registry-storage`)

The GitLab Container Registry uses its own independent storage engine syntax.

### Kubernetes Secret Specification
* **Secret Name:** `gitlab-registry-storage`
* **Secret Key:** `config`
* **Format:** YAML (Docker Registry S3 driver format)
* **Vault Source Path:** `kv/data/gitlab/object-storage/registry`

### Connection Configuration Format (`config`)
```yaml
s3:
  accesskey: "<REGISTRY_S3_ACCESS_KEY>"
  secretkey: "<REGISTRY_S3_SECRET_KEY>"
  region: us-east-1
  regionendpoint: https://s3.k8s.tss.local
  bucket: gitlab-registry
  secure: true
  v4auth: true
  pathstyle: true
  rootdirectory: /
  chunksize: 5242880
```

---

## 4. Group 3: Toolbox Backup Storage (`gitlab-backup-object-storage`)

Used by the GitLab Toolbox pod to upload and download full system backups (`gitlab-backup create` and `gitlab-backup restore`).

### Kubernetes Secret Specification
* **Secret Name:** `gitlab-backup-object-storage`
* **Secret Key:** `config`
* **Format:** INI (`s3cmd` configuration)
* **Vault Source Path:** `kv/data/gitlab/object-storage/backup`

### Connection Configuration Format (`config`)
```ini
[default]
access_key = <BACKUP_S3_ACCESS_KEY>
secret_key = <BACKUP_S3_SECRET_KEY>
bucket_location = us-east-1
host_base = s3.k8s.tss.local
# Path-style S3 endpoint; s3cmd appends the bucket to the request path.
host_bucket = s3.k8s.tss.local
use_https = True
signature_v2 = False
```

---

## 5. Helm Values Mapping

In [`helm-values/gitlab/values-production.yaml`](file:///opt/gitops-platform/helm-values/gitlab/values-production.yaml), these secrets are mapped as follows:

```yaml
global:
  appConfig:
    object_store:
      enabled: true
      connection:
        secret: gitlab-object-storage
        key: connection
      proxy_download: true

registry:
  enabled: true
  storage:
    secret: gitlab-registry-storage
    key: config

gitlab:
  toolbox:
    backups:
      objectStorage:
        config:
          secret: gitlab-backup-object-storage
          key: config
```

---

## 6. S3 IAM Least-Privilege Policy Summary

| Access Group | Permitted Actions | Target Buckets |
| :--- | :--- | :--- |
| **Rails IAM User** | `s3:GetObject`, `s3:PutObject`, `s3:DeleteObject`, `s3:ListBucket` | `arn:aws:s3:::gitlab-artifacts/*`, `arn:aws:s3:::gitlab-lfs/*`, `arn:aws:s3:::gitlab-uploads/*`, `arn:aws:s3:::gitlab-packages/*`, `arn:aws:s3:::gitlab-mr-diffs/*`, `arn:aws:s3:::gitlab-terraform-state/*`, `arn:aws:s3:::gitlab-dependency-proxy/*` |
| **Registry IAM User** | `s3:GetObject`, `s3:PutObject`, `s3:DeleteObject`, `s3:ListBucket` | `arn:aws:s3:::gitlab-registry/*` |
| **Backup IAM User** | `s3:GetObject`, `s3:PutObject`, `s3:DeleteObject`, `s3:ListBucket` | `arn:aws:s3:::gitlab-backups/*`, `arn:aws:s3:::gitlab-backup-tmp/*` |

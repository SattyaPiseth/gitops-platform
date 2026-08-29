# GitLab Object Storage Buckets Specification

> **Environment:** Production (`k8s.tss.local`)  
> **Target Platform:** GitLab CE & Container Registry  
> **Provider Compatibility:** AWS S3 / MinIO / Ceph S3  
> **Status:** Production Readiness Baseline  

---

## 1. Bucket Inventory & Purpose

GitLab application pods must not be responsible for long-term business data storage. Production data is segregated into 10 dedicated S3-compatible buckets based on data classification, lifecycle, and access boundaries:

| # | Bucket Name | Purpose & Content | Owner Component | Access Group |
| :-: | :--- | :--- | :--- | :--- |
| **1** | `gitlab-artifacts` | CI/CD build artifacts, job traces, test reports | GitLab Workhorse / Sidekiq | Rails S3 |
| **2** | `gitlab-lfs` | Git Large File Storage (LFS) objects | GitLab Workhorse / Rails | Rails S3 |
| **3** | `gitlab-uploads` | User/group avatars, markdown attachments, issue uploads | GitLab Workhorse / Rails | Rails S3 |
| **4** | `gitlab-packages` | Package registry binaries (npm, PyPI, Maven, Generic, etc.) | GitLab Workhorse / Rails | Rails S3 |
| **5** | `gitlab-mr-diffs` | External merge request diffs | GitLab Rails / Sidekiq | Rails S3 |
| **6** | `gitlab-terraform-state` | Terraform state files from CI/CD pipelines | GitLab Rails | Rails S3 |
| **7** | `gitlab-dependency-proxy`| Cached container image layers from upstream proxies | GitLab Workhorse / Rails | Rails S3 |
| **8** | `gitlab-registry` | OCI container registry images, manifests, and blobs | Container Registry | Registry S3 |
| **9** | `gitlab-backups` | Scheduled & on-demand full GitLab backup archives (`.tar`) | GitLab Toolbox | Backup S3 |
| **10**| `gitlab-backup-tmp` | Temporary restore & backup extraction staging area | GitLab Toolbox | Backup S3 |

---

## 2. Bucket Policies, Encryption, & Lifecycle Specifications

```text
┌─────────────────────────┬───────────────────┬─────────────────────┬──────────────────────────────┐
│ Bucket Name             │ Encryption (SSE)  │ Lifecycle / Expiry  │ Public Access Block / Policy │
├─────────────────────────┼───────────────────┼─────────────────────┼──────────────────────────────┤
│ gitlab-artifacts        │ Enabled (AES256)  │ Project artifact TTL│ Block All Public Access      │
│ gitlab-lfs              │ Enabled (AES256)  │ Repository Lifetime │ Block All Public Access      │
│ gitlab-uploads          │ Enabled (AES256)  │ Permanent           │ Block All Public Access      │
│ gitlab-packages         │ Enabled (AES256)  │ Package Retention   │ Block All Public Access      │
│ gitlab-mr-diffs         │ Enabled (AES256)  │ Permanent           │ Block All Public Access      │
│ gitlab-terraform-state  │ Enabled (AES256)  │ Versioned / Perm    │ Block All Public Access      │
│ gitlab-dependency-proxy │ Enabled (AES256)  │ 90 days TTL (Cache) │ Block All Public Access      │
│ gitlab-registry         │ Enabled (AES256)  │ Registry GC Cleanup │ Block All Public Access      │
│ gitlab-backups          │ Enabled (AES256)  │ 30–90 Days Policy   │ Block All Public Access      │
│ gitlab-backup-tmp       │ Enabled (AES256)  │ 7 Days Auto-Delete  │ Block All Public Access      │
└─────────────────────────┴───────────────────┴─────────────────────┴──────────────────────────────┘
```

---

## 3. Detailed Bucket Configurations

### 3.1 CI/CD Artifacts (`gitlab-artifacts`)
* **Data Class**: Ephemeral / Short-to-Medium Term CI output.
* **Encryption**: Server-Side Encryption (`AES256` or `aws:kms`).
* **Lifecycle Rules**: Governed by GitLab project artifact expiration settings (`artifacts_expire_in`). S3 lifecycle may transition objects older than 90 days to cold storage if applicable.
* **CORS**: Not required for direct upload unless direct client-side upload is enabled.

### 3.2 Git Large File Storage (`gitlab-lfs`)
* **Data Class**: Permanent Source Code Binary Assets.
* **Encryption**: Server-Side Encryption (`AES256`).
* **Lifecycle Rules**: Permanent (retention tied to repository lifecycle).
* **Versioning**: Recommended for disaster recovery against accidental deletion.

### 3.3 User & Issue Uploads (`gitlab-uploads`)
* **Data Class**: Persistent User Attachments (images, PDFs, documents attached to issues/MRs).
* **Encryption**: Server-Side Encryption (`AES256`).
* **Access Control**: Private. Workhorse proxies downloads with authentication verification (`proxy_download: true`).

### 3.4 Package Registry (`gitlab-packages`)
* **Data Class**: Software Release Packages.
* **Encryption**: Server-Side Encryption (`AES256`).
* **Lifecycle Rules**: Governed by GitLab package cleanup policies.

### 3.5 Merge Request Diffs (`gitlab-mr-diffs`)
* **Data Class**: Diff Metadata for Merge Requests.
* **Encryption**: Server-Side Encryption (`AES256`).
* **Lifecycle Rules**: Permanent or archived alongside closed/merged MRs.

### 3.6 Terraform State (`gitlab-terraform-state`)
* **Data Class**: Highly Sensitive Infrastructure State Files.
* **Encryption**: Mandatory Server-Side Encryption (`AES256`).
* **Versioning**: **Mandatory (Enabled)** to prevent state corruption during concurrent pipeline runs.

### 3.7 Dependency Proxy Cache (`gitlab-dependency-proxy`)
* **Data Class**: Cached Upstream Container Image Layers.
* **Lifecycle Rules**: Auto-expire cached layers after 90 days of inactivity.

### 3.8 Container Registry (`gitlab-registry`)
* **Data Class**: Production OCI Container Images.
* **Encryption**: Server-Side Encryption (`AES256`).
* **Access**: Restricted exclusively to GitLab Container Registry credentials.
* **CORS Policy**:
  ```json
  [
    {
      "AllowedHeaders": ["*"],
      "AllowedMethods": ["GET", "HEAD", "PUT", "DELETE"],
      "AllowedOrigins": ["https://registry.k8s.tss.local"],
      "ExposeHeaders": ["ETag"],
      "MaxAgeSeconds": 3000
    }
  ]
  ```

### 3.9 Backup Archive Storage (`gitlab-backups`)
* **Data Class**: Full Disaster Recovery Archives (`.tar`).
* **Retention Policy**: 30 to 90 days rolling retention.
* **Access**: Restricted exclusively to GitLab Toolbox backup role.

### 3.10 Temporary Backup Staging (`gitlab-backup-tmp`)
* **Data Class**: Transient staging files created during backup extraction or restore.
* **Lifecycle Rules**: Auto-delete all objects after **7 days** to avoid disk/bucket waste.

---

## 4. Verification Checklist Before GitLab Deployment

- [ ] All 10 buckets created in S3 / MinIO backend.
- [ ] Server-Side Encryption enabled on all buckets.
- [ ] Public access block enabled across all buckets.
- [ ] CORS policy applied to `gitlab-registry`.
- [ ] S3 IAM users / service accounts created with least privilege per access group (Rails, Registry, Backup).

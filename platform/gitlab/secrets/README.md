# GitLab Secrets & Credential Delivery Architecture

> **Status:** Production Secrets Baseline  
> **Target Namespace:** `gitlab`  
> **Secret Authority:** HashiCorp Vault (`https://vault.k8s.tss.local`)
> **Synchronization Layer:** Vault Secrets Operator (VSO)  
> **GitOps Controller:** Argo CD (`platform/gitlab`)  

---

## 1. Core Principles & Separation of Concerns

### Infrastructure Configuration (In Git)
The following parameters describe topology, hostnames, ports, database names, and non-sensitive settings. They reside in GitOps Helm values ([`helm-values/gitlab/values-production.yaml`](../../../helm-values/gitlab/values-production.yaml)):
* PostgreSQL Host: `gitlab-postgresql-rw.gitlab.svc.cluster.local`, Port: `5432`, Database: `gitlabhq_production`, User: `gitlab`
* Redis Sentinel: master group `mymaster`, discovery service `gitlab-redis-s-hl.gitlab.svc.cluster.local:26379`, authentication enabled
* Object Storage: Endpoint: `https://s3.k8s.tss.local`, Bucket names, `proxy_download: true`
* Runner Configuration: `gitlabUrl: https://gitlab.k8s.tss.local/`, concurrency: `10`, images, resources

### Sensitive Credentials (In Vault)
The actual passwords, API tokens, and secret access keys live exclusively inside HashiCorp Vault:
* PostgreSQL user password
* Redis authentication password
* Rails S3 access and secret keys
* Container Registry S3 access and secret keys
* Backup S3 access and secret keys
* GitLab Runner authentication token
* SMTP relay username and password

---

## 2. Secret Delivery Responsibility Model

```text
GitHub / Argo CD
    │
    │ 1. Manages declarative desired state (VaultAuth & VaultStaticSecret)
    ▼
Vault Secrets Operator (VSO)
    │
    │ 2. Authenticates to Vault using workload ServiceAccounts
    ▼
HashiCorp Vault
    │
    │ 3. Evaluates least-privilege policies and returns approved secrets
    ▼
Kubernetes Secrets (gitlab namespace)
    │
    │ 4. VSO creates and reconciles runtime delivery objects
    ▼
GitLab CE & GitLab Runner
```

```
┌────────────────────────────────────────────────────────┐
│ Ownership Boundaries                                   │
├────────────────────────────────────────────────────────┤
│ • Git / GitHub          ──> NO secrets or passwords    │
│ • Argo CD               ──> NO Vault root tokens       │
│ • Kubernetes Secrets    ──> Runtime delivery only      │
│ • VSO                   ──> Sole secret reconciler     │
│ • HashiCorp Vault       ──> Authoritative source truth │
└────────────────────────────────────────────────────────┘
```

---

## 3. Complete Kubernetes Secret Catalog

| Kubernetes Secret Name | Required Key | Value Description | Vault Source Path | Consumed By |
| :--- | :--- | :--- | :--- | :--- |
| `gitlab-postgresql` | `password` | PostgreSQL database user password | `kv/data/gitlab/postgresql` | Webservice, Sidekiq, Toolbox, Migrations |
| `gitlab-redis` | `password` | Redis authentication password | `kv/data/gitlab/redis` | Webservice, Sidekiq, KAS, Mailroom |
| `gitlab-object-storage` | `connection` | S3 Fog connection YAML block | `kv/data/gitlab/object-storage/rails` | Webservice, Sidekiq, Workhorse, Toolbox |
| `gitlab-registry-storage`| `config` | Docker Registry S3 YAML block | `kv/data/gitlab/object-storage/registry`| Container Registry |
| `gitlab-backup-object-storage` | `config` | Backup s3cmd configuration block | `kv/data/gitlab/object-storage/backup` | Toolbox Backup Utility |
| `gitlab-runner-secret` | `runner-token` | Runner registration/auth token | `kv/data/gitlab-runner/auth` | GitLab Runner Manager |
| `gitlab-smtp` | `username`, `password` | Dedicated SMTP relay credentials | `kv/data/gitlab/smtp` | Webservice, Sidekiq, Toolbox |

---

## 4. Distinct Trust Boundaries & Blast-Radius Reduction

GitLab CE and GitLab Runner operate under **separate identity and trust boundaries**:

```text
GitLab CE Platform
  │
  ├── ServiceAccount: gitlab:gitlab-vault-auth
  ├── Vault Role:     gitlab-platform
  └── Vault Policy:   gitlab-platform
                      ├── kv/data/gitlab/postgresql
                      ├── kv/data/gitlab/redis
                      ├── kv/data/gitlab/smtp
                      └── kv/data/gitlab/object-storage/*

GitLab Runner
  │
  ├── ServiceAccount: gitlab:gitlab-runner-vault-auth
  ├── Vault Role:     gitlab-runner
  └── Vault Policy:   gitlab-runner-read
                      └── kv/data/gitlab-runner/auth
```

> **Security Benefit:** If a CI/CD job compromises the GitLab Runner pod, the attacker cannot obtain the database password, Redis credentials, or administrative S3 keys.

---

## 5. SMTP2GO Bootstrap and Rollout

1. Add and verify the sending domain `gitlab-mail.memora-shine.shop` in
   SMTP2GO under **Sending > Verified Senders > Sender domains**. Publish the
   exact CNAME records supplied by SMTP2GO and wait until the domain is shown
   as verified. Keep DMARC managed separately in DNS.
2. Grant `gitlab-platform` read-only access to the SMTP secret:

   ```hcl
   path "kv/data/gitlab/smtp" {
     capabilities = ["read"]
   }
   ```

3. Under SMTP2GO **Sending > SMTP Users**, create a dedicated SMTP user for
   GitLab. Do not use the SMTP2GO dashboard password or an API key.
4. Store both values in Vault without putting either one in shell history or
   Git:

   ```bash
   kubectl exec -n vault -it vault-0 -- sh
   export VAULT_ADDR=https://vault-active.vault.svc.cluster.local:8200
   vault login
   read -p "GitLab SMTP username: " GITLAB_SMTP_USERNAME
   read -s -p "GitLab SMTP password: " GITLAB_SMTP_PASSWORD
   echo
   vault kv put kv/gitlab/smtp \
     username="$GITLAB_SMTP_USERNAME" \
     password="$GITLAB_SMTP_PASSWORD"
   unset GITLAB_SMTP_USERNAME GITLAB_SMTP_PASSWORD
   ```

5. Confirm `VaultStaticSecret/gitlab-smtp` is synced and the generated Secret
   contains both expected key names. Do not print or decode their values.
6. Sync `gitlab-prerequisites`, then `gitlab`. VSO automatically restarts the
   Webservice, Sidekiq, and Toolbox deployments whenever this secret rotates.
7. Send a test message and confirm delivery in SMTP2GO **Reports > Activity**.
8. Only after successful delivery, enable **Hard** email confirmation in
   **Admin > Settings > General > New user account restrictions**.

Do not enable hard confirmation before the test succeeds; doing so can prevent
new users from signing in while mail delivery is unavailable.

---

## 6. Definition of "Ready" Checklist

Before proceeding to deploy GitLab CE:

- [ ] **PostgreSQL**: Reachable at `gitlab-postgresql-rw.gitlab.svc.cluster.local:5432`, `gitlabhq_production` DB created, user `gitlab` granted privileges and required extensions (`pg_trgm`, `btree_gist`, `amcheck`).
- [ ] **Redis**: Three replication pods and three Sentinel pods ready; `mymaster` is discoverable through `gitlab-redis-s-hl.gitlab.svc.cluster.local:26379`; password authentication active.
- [ ] **Object Storage**: All 10 buckets created in S3 backend; S3 credentials tested for Rails, Registry, and Backup.
- [ ] **Vault**: KV v2 engine enabled; secrets populated under `kv/data/gitlab/*` and `kv/data/gitlab-runner/*`.
- [ ] **Vault Policies & Roles**: `gitlab-platform` and `gitlab-runner` roles configured and bound to their respective Kubernetes ServiceAccounts.
- [ ] **SMTP2GO**: Sender domain verified; provider-issued DNS records pass; dedicated SMTP credentials are stored at `kv/gitlab/smtp`.
- [ ] **VSO Sync**: `VaultStaticSecret` CRDs synced; all 7 Kubernetes Secrets generated in `gitlab` namespace.
- [ ] **SMTP Test**: Test email delivered before hard email confirmation is enabled.

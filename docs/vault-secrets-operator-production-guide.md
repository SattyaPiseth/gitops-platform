# HashiCorp Vault Secrets Operator (VSO) Production GitOps Guide

> **Status:** Production baseline  
> **Component:** Vault Secrets Operator (VSO) & HashiCorp Vault Integration  
> **Target Secret:** `grafana-admin-credentials` (`monitoring` namespace)  
> **Chart:** `hashicorp/vault-secrets-operator` `0.9.1`  
> **Vault Endpoint:** `https://vault.k8s.tss.local:8200`  
> **Vault Secret Path:** `kv/data/monitoring/grafana`  
> **GitOps Controller:** Argo CD  
> **Repository:** `https://github.com/SattyaPiseth/gitops-platform.git`  

---

## 1. Purpose & Core Goal

The purpose of this architecture is to integrate **HashiCorp Vault** with the Kubernetes GitOps platform so that Grafana credentials are managed securely and automatically, without putting sensitive values in Git or creating Kubernetes Secrets manually.

```text
HashiCorp Vault
      ↓ (Secure HTTPS & Kubernetes Identity Auth)
Vault Secrets Operator (VSO)
      ↓ (Auto-reconciles)
Kubernetes Secret (monitoring:grafana-admin-credentials)
      ↓ (Standard Helm pattern: existingSecret)
kube-prometheus-stack Grafana
```

---

## 2. Architecture & Responsibility Model

```text
GitHub / Argo CD
    │
    │ 1. Manages configuration & desired state (declarative CRDs)
    ▼
Vault Secrets Operator (VSO)
    │
    │ 2. Authenticates securely using monitoring:grafana-vault-auth ServiceAccount
    ▼
HashiCorp Vault
    │
    │ 3. Validates K8s token & returns authorized secret (kv/data/monitoring/grafana)
    ▼
Kubernetes Secret (monitoring:grafana-admin-credentials)
    │
    ▼
kube-prometheus-stack (Grafana)
```

### Security Boundaries

```text
GitHub
  └── NO passwords or sensitive data in Git

Argo CD
  └── NO Vault root token or direct secret credentials

Grafana
  └── NO direct Vault network access or Vault tokens required

Vault Secrets Operator
  └── Only component authenticating to Vault to retrieve the secret

Vault
  └── Authoritative secret store with centralized rotation & audit logging
```

---

## 3. GitOps Component Structure

| File Path | Description |
| :--- | :--- |
| [`clusters/production/argocd/applications/vault-secrets-operator.yaml`](file:///opt/gitops-platform/clusters/production/argocd/applications/vault-secrets-operator.yaml) | Argo CD Application deploying VSO into `vault-secrets-operator-system`. |
| [`helm-values/vault-secrets-operator/values.yaml`](file:///opt/gitops-platform/helm-values/vault-secrets-operator/values.yaml) | Production Helm values (replicas, resource requests/limits, telemetry). |
| [`clusters/production/argocd/resources/vault-secrets-operator/namespace.yaml`](file:///opt/gitops-platform/clusters/production/argocd/resources/vault-secrets-operator/namespace.yaml) | Namespace `vault-secrets-operator-system`. |
| [`clusters/production/argocd/resources/vault-secrets-operator/vault-connection.yaml`](file:///opt/gitops-platform/clusters/production/argocd/resources/vault-secrets-operator/vault-connection.yaml) | `VaultConnection` CR pointing to `https://vault.k8s.tss.local:8200`. |
| [`clusters/production/argocd/resources/kube-prometheus-stack/grafana-vault-auth.yaml`](file:///opt/gitops-platform/clusters/production/argocd/resources/kube-prometheus-stack/grafana-vault-auth.yaml) | ServiceAccount & `VaultAuth` CR for `monitoring:grafana-vault-auth`. |
| [`clusters/production/argocd/resources/kube-prometheus-stack/grafana-vault-static-secret.yaml`](file:///opt/gitops-platform/clusters/production/argocd/resources/kube-prometheus-stack/grafana-vault-static-secret.yaml) | `VaultStaticSecret` CR creating `Secret/grafana-admin-credentials`. |
| [`helm-values/kube-prometheus-stack/values.yaml`](file:///opt/gitops-platform/helm-values/kube-prometheus-stack/values.yaml) | Grafana Helm values referencing `existingSecret: grafana-admin-credentials`. |

---

## 4. Step-by-Step Vault Server Configuration Runbook

Execute the following commands on your HashiCorp Vault server (via Vault CLI or API).

### Step 1: Enable the KV v2 Secret Engine
If KV v2 is not already mounted at `kv`:
```bash
export VAULT_ADDR="https://vault.k8s.tss.local:8200"

# Enable KV v2 secret engine at path 'kv'
vault secrets enable -path=kv kv-v2
```

### Step 2: Store the Grafana Admin Secret in Vault
Write the secret containing `admin-user` and `admin-password` to `kv/monitoring/grafana`:
```bash
vault kv put kv/monitoring/grafana \
  admin-user="admin" \
  admin-password="<YOUR_STRONG_GRAFANA_PASSWORD>"
```

### Step 3: Create the Least-Privilege Vault ACL Policy
Create a policy file named `grafana-monitoring-policy.hcl`:
```hcl
path "kv/data/monitoring/grafana" {
  capabilities = ["read"]
}
```

Write the policy to Vault:
```bash
vault policy write grafana-monitoring-read grafana-monitoring-policy.hcl
```

### Step 4: Enable & Configure the Kubernetes Auth Method
Enable the Kubernetes authentication method in Vault (if not already enabled):
```bash
vault auth enable kubernetes
```

Configure Vault with the Kubernetes cluster API credentials:
```bash
# Obtain Kubernetes host and CA certificate from the cluster
K8S_HOST="https://kubernetes.default.svc"
K8S_CACERT="$(kubectl config view --raw --minify --flatten -o jsonpath='{.clusters[0].cluster.certificate-authority-data}' | base64 -d)"

vault write auth/kubernetes/config \
  kubernetes_host="${K8S_HOST}" \
  kubernetes_ca_cert="${K8S_CACERT}"
```

### Step 5: Bind the Vault Role to the Kubernetes ServiceAccount
Create the role `grafana-monitoring` granting access to the `monitoring:grafana-vault-auth` ServiceAccount:
```bash
vault write auth/kubernetes/role/grafana-monitoring \
  bound_service_account_names=grafana-vault-auth \
  bound_service_account_namespaces=monitoring \
  policies=grafana-monitoring-read \
  ttl=1h
```

---

## 5. Verification & Day-2 Operations

### 1. Verify Argo CD Synchronization
Sync the applications in Argo CD:
```bash
# Verify VSO is healthy and synced
kubectl get application -n argocd vault-secrets-operator

# Verify kube-prometheus-stack is synced
kubectl get application -n argocd kube-prometheus-stack
```

### 2. Verify VSO Custom Resources
Check the status of the `VaultConnection`, `VaultAuth`, and `VaultStaticSecret`:
```bash
# Check VaultConnection
kubectl get vaultconnections.secrets.hashicorp.com -n vault-secrets-operator-system

# Check VaultAuth
kubectl get vaultauths.secrets.hashicorp.com -n monitoring grafana-vault-auth

# Check VaultStaticSecret
kubectl get vaultstaticsecrets.secrets.hashicorp.com -n monitoring grafana-admin-credentials
```

### 3. Verify Generated Kubernetes Secret
Ensure VSO has created the Kubernetes Secret in the `monitoring` namespace:
```bash
kubectl get secret -n monitoring grafana-admin-credentials
```

Inspect secret keys without exposing the password:
```bash
kubectl get secret -n monitoring grafana-admin-credentials -o jsonpath='{.data}'
# Expected output keys: admin-password, admin-user
```

### 4. Verify Grafana Login
Open Grafana at:
```text
https://grafana.k8s.tss.local
```
Log in using `admin` and the password configured in Vault.

### 5. Centralized Secret Rotation
To rotate the Grafana password in the future:
1. Update the secret in Vault:
   ```bash
   vault kv put kv/monitoring/grafana admin-user="admin" admin-password="<NEW_STRONG_PASSWORD>"
   ```
2. VSO will automatically detect the new version within the `syncPeriod` (5 minutes) and update the `grafana-admin-credentials` Kubernetes Secret.
3. Grafana will consume the updated secret on next authentication / reload.

---

## 6. Troubleshooting Matrix

| Issue | Likely Cause | Resolution |
| :--- | :--- | :--- |
| `VaultStaticSecret` status `SecretSynced=False` | `VaultAuth` authentication failure | Check VSO controller logs: `kubectl logs -n vault-secrets-operator-system -l app.kubernetes.io/name=vault-secrets-operator`. Verify `monitoring:grafana-vault-auth` exists. |
| `permission denied` in Vault logs | Policy mismatch or wrong secret path | Verify role policy `grafana-monitoring-read` contains `kv/data/monitoring/grafana` and capabilities `["read"]`. |
| `TLS certificate verification failed` | Missing or untrusted CA certificate | Ensure Vault certificate is issued by `k8s-internal-ca` or configure `caCertSecretRef` in `VaultConnection`. |
| Grafana pod restarts / cannot start | Secret `grafana-admin-credentials` not found | Ensure Vault secret exists before Grafana deployment starts. |

---

## 7. GitLab CE & GitLab Runner Vault Setup Runbook

### Step 1: Populate GitLab Secrets in Vault

```bash
# 1. PostgreSQL Database Password
vault kv put kv/gitlab/postgresql password="<STRONG_POSTGRES_PASSWORD>"

# 2. Redis Authentication Password
vault kv put kv/gitlab/redis password="<STRONG_REDIS_PASSWORD>"

# 3. Rails Consolidated Object Storage (Fog S3 format)
vault kv put kv/gitlab/object-storage/rails connection="provider: AWS
region: us-east-1
aws_access_key_id: <RAILS_S3_ACCESS_KEY>
aws_secret_access_key: <RAILS_S3_SECRET_KEY>
host: s3.k8s.tss.local
endpoint: https://s3.k8s.tss.local
path_style: true
aws_signature_version: 4"

# 4. Container Registry S3 Storage (Docker Registry format)
vault kv put kv/gitlab/object-storage/registry config="s3:
  accesskey: <REGISTRY_S3_ACCESS_KEY>
  secretkey: <REGISTRY_S3_SECRET_KEY>
  region: us-east-1
  regionendpoint: https://s3.k8s.tss.local
  bucket: gitlab-registry
  secure: true
  v4auth: true
  rootdirectory: /
  chunksize: 5242880"

# 5. Toolbox Backup S3 Storage (s3cmd format)
vault kv put kv/gitlab/object-storage/backup config="[default]
access_key = <BACKUP_S3_ACCESS_KEY>
secret_key = <BACKUP_S3_SECRET_KEY>
bucket_location = us-east-1
host_base = s3.k8s.tss.local
host_bucket = s3.k8s.tss.local/%(bucket)
use_https = True
signature_v2 = False"

# 6. GitLab Runner Authentication Token
vault kv put kv/gitlab-runner/auth runner-token="<GITLAB_RUNNER_AUTHENTICATION_TOKEN>"
```

### Step 2: Create Least-Privilege Vault ACL Policies

Create `gitlab-platform-policy.hcl`:
```hcl
path "kv/data/gitlab/*" {
  capabilities = ["read"]
}
```

Create `gitlab-runner-policy.hcl`:
```hcl
path "kv/data/gitlab-runner/auth" {
  capabilities = ["read"]
}
```

Apply policies to Vault:
```bash
vault policy write gitlab-platform-read gitlab-platform-policy.hcl
vault policy write gitlab-runner-read gitlab-runner-policy.hcl
```

### Step 3: Bind Kubernetes Roles

```bash
# Bind GitLab CE platform role to gitlab:gitlab-vault-auth
vault write auth/kubernetes/role/gitlab-platform \
  bound_service_account_names=gitlab-vault-auth \
  bound_service_account_namespaces=gitlab \
  policies=gitlab-platform-read \
  ttl=1h

# Bind GitLab Runner role to gitlab:gitlab-runner-vault-auth
vault write auth/kubernetes/role/gitlab-runner \
  bound_service_account_names=gitlab-runner-vault-auth \
  bound_service_account_namespaces=gitlab \
  policies=gitlab-runner-read \
  ttl=1h
```

---

## 8. Reusability Roadmap

This architecture is modular and ready to manage secrets across all other platform components:

```text
kv/data/
  ├── monitoring/grafana          ──> Secret/grafana-admin-credentials (monitoring)
  ├── gitlab/
  │   ├── postgresql              ──> Secret/gitlab-postgresql (gitlab)
  │   ├── redis                   ──> Secret/gitlab-redis (gitlab)
  │   └── object-storage/
  │       ├── rails               ──> Secret/gitlab-object-storage (gitlab)
  │       ├── registry            ──> Secret/gitlab-registry-storage (gitlab)
  │       └── backup              ──> Secret/gitlab-backup-object-storage (gitlab)
  ├── gitlab-runner/auth          ──> Secret/gitlab-runner-secret (gitlab)
  └── cnpg/cluster-superuser      ──> Secret/cnpg-superuser-creds (cnpg-system)
```
Each workload simply defines its own `ServiceAccount`, `VaultAuth` (scoped to its own Vault role), and `VaultStaticSecret`.


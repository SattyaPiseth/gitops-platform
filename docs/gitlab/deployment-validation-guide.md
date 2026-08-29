# GitLab CE Production Security Hardening & Deployment Validation Guide

> **Status:** Production Baseline & Acceptance Gate  
> **Target System:** GitLab Community Edition (CE) & GitLab Runner  
> **Environment:** Production (`k8s.tss.local`)  
> **Core Philosophy:** *Do not consider GitLab production-ready simply because every pod is `Running`; consider it production-ready only when required flows are proven, forbidden flows are blocked, credentials are automated, GitOps self-healing works, monitoring detects failures, and a real backup can be restored successfully.*

---

## 1. Overview of the 5 Validation Pillars

```text
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                 5 Pillars of Production Readiness                      │
├───────────────────────┬───────────────────────┬───────────────────────┬────────────────┤
│ 1. Access Control     │ 2. Network Isolation  │ 3. Secret Security    │ 4. Resilience  │
│    • BasicAuth on Mon │    • Default Deny     │    • Zero Git secrets │    • PDBs      │
│    • Least Privilege  │    • Workload-level   │    • VSO auto-sync    │    • Self-heal │
│    • Scoped AppProject│    • No Vault Egress  │    • Identity tokens  │    • Restore   │
└───────────────────────┴───────────────────────┴───────────────────────┴────────────────┘
```

---

## 2. External Access & Ingress Hardening

### 2.1 Administrative Ingress Authentication
Administrative endpoints (Prometheus and Alertmanager) are protected behind Traefik's `monitoring-basic-auth` middleware:

```text
Users / Admins ──► Traefik Ingress (HTTPS) ──► monitoring-basic-auth ──► Prometheus / Alertmanager
```

### 2.2 Verification Command
```bash
# 1. Verify unauthenticated request returns 401 Unauthorized
curl -k -I https://prometheus.k8s.tss.local
curl -k -I https://alertmanager.k8s.tss.local
# Expected: HTTP/2 401 Unauthorized

# 2. Verify authenticated request succeeds with Vault-managed credentials
curl -k -u "admin:<PASSWORD>" -I https://prometheus.k8s.tss.local
# Expected: HTTP/2 200 OK
```

---

## 3. Least-Privilege GitOps RBAC Verification

The `platform` and `gitlab` Argo CD `AppProject` definitions enforce strict blast-radius isolation:

```bash
# Verify gitlab AppProject cannot manage cluster-wide resources (except Namespace)
kubectl get appproject -n argocd gitlab -o yaml | grep -A 10 clusterResourceWhitelist
# Expected: Only group: "", kind: Namespace

# Verify platform AppProject whitelist is explicitly scoped (no wildcards "*")
kubectl get appproject -n argocd platform -o yaml | grep -A 20 clusterResourceWhitelist
```

---

## 4. Zero-Trust Network Policy Testing

### 4.1 Security Boundary Matrix

| Source | Destination | Expected Result | Why |
| :--- | :--- | :---: | :--- |
| Traefik Ingress | GitLab Webservice (`8181`/`8080`) | **ALLOW** | Normal user HTTP/HTTPS traffic |
| Traefik Ingress | GitLab Registry (`5000`) | **ALLOW** | Container image push/pull |
| Traefik Ingress | GitLab Shell (`2222`) | **ALLOW** | Git over SSH |
| GitLab Webservice | PostgreSQL (`5432`) | **ALLOW** | Core application database access |
| GitLab Webservice | Redis (`6379`) | **ALLOW** | Cache & session management |
| GitLab Webservice | S3 Object Storage (`443`) | **ALLOW** | File & artifact upload/download |
| GitLab Workload | **Vault Server (`8200`)** | **DENIED** 🛑 | **Workloads must never access Vault directly** |
| Random Namespace | GitLab Webservice | **DENIED** 🛑 | Inter-namespace isolation |
| Random Namespace | PostgreSQL / Redis | **DENIED** 🛑 | Data tier isolation |

### 4.2 Network Policy Verification Drills

```bash
# Test 1: Positive Test - Webservice connects to PostgreSQL
kubectl exec -n gitlab -it deploy/gitlab-webservice-default -- nc -zv postgres.k8s.tss.local 5432
# Expected: Connection to postgres.k8s.tss.local 5432 port [tcp/postgresql] succeeded!

# Test 2: Negative Test - GitLab workload attempting to contact Vault directly (Must be BLOCKED)
kubectl exec -n gitlab -it deploy/gitlab-webservice-default -- nc -zvw3 vault.k8s.tss.local 8200
# Expected: Connection timed out / Operation not permitted

# Test 3: Negative Test - Traffic from an unauthorized namespace (Must be BLOCKED)
kubectl run netpol-test --rm -it --image=busybox -n default -- nc -zvw3 gitlab-webservice-default.gitlab.svc 8181
# Expected: Connection timed out
```

---

## 5. Secret Delivery & VSO Integrity Checklist

Verify that Vault Secrets Operator successfully delivered all required Kubernetes Secrets:

```bash
# Check status of all VaultStaticSecrets in gitlab namespace
kubectl get vaultstaticsecrets.secrets.hashicorp.com -n gitlab

# Verify destination Secret existence and keys without exposing sensitive values
kubectl get secret -n gitlab gitlab-postgresql -o jsonpath='{.data}' | grep -q 'password' && echo "✓ gitlab-postgresql valid"
kubectl get secret -n gitlab gitlab-redis -o jsonpath='{.data}' | grep -q 'password' && echo "✓ gitlab-redis valid"
kubectl get secret -n gitlab gitlab-object-storage -o jsonpath='{.data}' | grep -q 'connection' && echo "✓ gitlab-object-storage valid"
kubectl get secret -n gitlab gitlab-registry-storage -o jsonpath='{.data}' | grep -q 'config' && echo "✓ gitlab-registry-storage valid"
kubectl get secret -n gitlab gitlab-backup-object-storage -o jsonpath='{.data}' | grep -q 'config' && echo "✓ gitlab-backup-object-storage valid"
kubectl get secret -n gitlab gitlab-runner-secret -o jsonpath='{.data}' | grep -q 'runner-token' && echo "✓ gitlab-runner-secret valid"
```

---

## 6. GitOps Lifecycle & Self-Healing Drift Drill

Prove that Git is the sole authority and Argo CD automatically heals drift:

```bash
# 1. Intentionally modify a resource manually (e.g. edit replica count or label)
kubectl scale deployment -n gitlab gitlab-sidekiq-all-in-1-v2 --replicas=5

# 2. Verify Argo CD detects OutOfSync
kubectl get application -n argocd gitlab -o jsonpath='{.status.sync.status}'

# 3. Verify Argo CD selfHeal restores desired Git state (replicas: 2)
sleep 15
kubectl get deployment -n gitlab gitlab-sidekiq-all-in-1-v2 -o jsonpath='{.spec.replicas}'
# Expected: 2
```

---

## 7. External Stateful Dependencies Validation

### 7.1 PostgreSQL Migration & Query Test
```bash
# Verify database migrations completed cleanly
kubectl logs -n gitlab -l app=migrations --tail=50 | grep "All migrations up to date"

# Verify active connections and extensions in PostgreSQL
# Extensions required: pg_trgm, btree_gist, amcheck
```

### 7.2 Redis Application Operation Test
```bash
# Verify Sidekiq is actively processing jobs via Redis
kubectl logs -n gitlab -l app=sidekiq --tail=50 | grep "Sidekiq.*running"
```

### 7.3 S3 Object Storage Feature-by-Feature Test

| Feature | Verification Action | Success Criteria |
| :--- | :--- | :--- |
| **Uploads** | Upload user avatar or issue attachment | File renders cleanly in UI; object appears in `gitlab-uploads` bucket |
| **LFS** | Commit a binary file (>10MB) via Git LFS | `git lfs push origin main` succeeds; object in `gitlab-lfs` |
| **Packages** | Publish an npm or generic package | Package appears in Package Registry; binary in `gitlab-packages` |
| **Registry** | Build & push container image | `docker push registry.k8s.tss.local/root/demo:v1` succeeds; blobs in `gitlab-registry` |
| **Backups** | Execute manual backup task | `gitlab-backup create` completes; archive uploaded to `gitlab-backups` |

---

## 8. TLS & Certificate Validation

Inspect certificate chains, SANs, and expiry dates:

```bash
for HOST in gitlab.k8s.tss.local registry.k8s.tss.local kas.k8s.tss.local; do
  echo "=== Checking TLS for ${HOST} ==="
  echo | openssl s_client -servername ${HOST} -connect ${HOST}:443 2>/dev/null | openssl x509 -noout -issuer -subject -dates
done
```

---

## 9. Real End-to-End CI/CD Pipeline Execution

Create a test repository with `.gitlab-ci.yml`:

```yaml
stages:
  - build
  - test

build_job:
  stage: build
  script:
    - echo "Testing GitOps Runner Execution"
    - uname -a
    - mkdir -p build && echo "Build OK" > build/artifact.txt
  artifacts:
    paths:
      - build/artifact.txt

test_job:
  stage: test
  script:
    - cat build/artifact.txt | grep "Build OK"
```

* **Success Criteria**:
  1. Runner pod dynamically spawns in `gitlab` namespace.
  2. Job clones repository and runs commands without root/privileged escalations.
  3. Artifact uploads successfully to S3 `gitlab-artifacts` bucket.
  4. Pipeline passes with green checkmark in GitLab UI.

---

## 10. Disaster Recovery Drill & RPO/RTO Measurement

### 10.1 Backup Execution
```bash
# Run backup in GitLab Toolbox pod
kubectl exec -n gitlab -it $(kubectl get pod -n gitlab -l app=toolbox -o jsonpath='{.items[0].metadata.name}') -- gitlab-backup create
```

### 10.2 Restore Drill in Controlled Environment
1. Record start timestamp ($T_{start}$).
2. Create test repository and issue before backup.
3. Simulate data loss or restore to staging target.
4. Execute `gitlab-backup restore BACKUP=<TIMESTAMP>`.
5. Record completion timestamp ($T_{end}$).
6. Calculate **RTO** ($T_{end} - T_{start}$) and verify zero data loss (**RPO = 0** for captured backup window).

---

## 11. Final Production Acceptance Gate Checklist

```text
[ ] Security
    [x] Administrative endpoints protected with BasicAuth
    [x] AppProjects locked down with least-privilege whitelists
    [x] Zero-trust NetworkPolicies active (Ingress & Egress deny by default)
    [x] GitLab workloads blocked from accessing Vault directly
    [x] Zero plaintext secrets committed in Git

[ ] GitOps & Automation
    [x] Root App-of-Apps manages all platform dependencies
    [x] Automated sync and self-healing verified

[ ] Stateful Dependencies
    [x] PostgreSQL connection, privileges, and migrations verified
    [x] Redis authentication and caching verified
    [x] All 10 S3 buckets configured with SSE and lifecycle policies
    [x] VSO generates all 6 required Kubernetes Secrets

[ ] Operations & Recovery
    [x] End-to-end CI/CD pipeline tested with GitLab Runner
    [x] Prometheus scraping and Alertmanager routing active
    [x] Full backup created and restore verified with documented RPO/RTO
```

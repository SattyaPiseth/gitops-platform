# kubelet-csr-approver Production GitOps Architecture & Operations Guide

> **Status:** Production migration baseline  
> **Component:** kubelet-csr-approver  
> **Current chart:** `kubelet-csr-approver-1.1.0`  
> **Current app version:** `v1.1.0`  
> **Namespace:** `kube-system`  
> **GitOps controller:** Argo CD  
> **Repository:** `https://github.com/SattyaPiseth/gitops-platform.git`  
> **Cluster role:** automatic validation/approval of `kubernetes.io/kubelet-serving` CSRs

---

## 1. Purpose

This document defines the production architecture, migration procedure, validation controls, rollback process, operational rules, and hardening roadmap for managing `kubelet-csr-approver` through Argo CD and GitOps.

The design intentionally separates:

1. **GitOps adoption** of the existing production release.
2. **Future upgrades** of the chart/application.
3. **Future security hardening** of CSR policy.
4. **Future monitoring enhancements** such as `ServiceMonitor`.

The first migration must preserve current behavior.

---

## 2. Why this component is security-sensitive

`kubelet-csr-approver` is not a normal stateless utility.

Kubernetes uses `CertificateSigningRequest` resources for certificate issuance. Kubelets use the signer:

```text
kubernetes.io/kubelet-serving
```

for serving certificates used on kubelet TLS endpoints.

Kubernetes does **not** automatically approve `kubernetes.io/kubelet-serving` requests using the built-in kube-controller-manager approver. This external controller exists specifically to validate and approve or deny those requests.

Therefore this controller participates in the node TLS trust path.

A configuration error could approve a serving certificate with an invalid hostname or IP SAN.

### Official references

- kubelet-csr-approver:
  https://github.com/postfinance/kubelet-csr-approver
- Kubernetes CSR API:
  https://kubernetes.io/docs/reference/kubernetes-api/certificates/certificate-signing-request-v1/
- Kubernetes certificates and CSR:
  https://kubernetes.io/docs/reference/access-authn-authz/certificate-signing-requests/

---

## 3. Existing production state

The existing Helm release is:

```text
Release:       kubelet-csr-approver
Namespace:     kube-system
Revision:      2
Chart:         kubelet-csr-approver-1.1.0
App version:   v1.1.0
Status:        deployed
Replicas:      2
```

Current intentional production overrides:

```yaml
bypassDnsResolution: false
bypassHostnameCheck: false

providerRegex: '^ubuntu-24-04-(mgmt|wrk)-0[1-3]$'

providerIpPrefixes: >-
  172.16.6.20/32,
  172.16.6.21/32,
  172.16.6.22/32,
  172.16.6.23/32,
  172.16.6.24/32,
  172.16.6.25/32
```

Current computed behavior also includes:

```text
replicas:                  2
leaderElection:            true
allowedDnsNames:           1
ignoreNonSystemNode:       false
rbac.manage:               true
serviceAccount.create:     true
metrics.enable:            true
metrics.serviceMonitor:    false
metrics.port:              8080
maxExpirationSeconds:      unset
```

Current security context:

```yaml
securityContext:
  allowPrivilegeEscalation: false
  capabilities:
    drop:
      - all
  privileged: false
  readOnlyRootFilesystem: true
  runAsGroup: 65532
  runAsNonRoot: true
  runAsUser: 65532
  seccompProfile:
    type: RuntimeDefault
```

Current control-plane toleration:

```yaml
tolerations:
  - effect: NoSchedule
    key: node-role.kubernetes.io/control-plane
    operator: Equal
```

Current live resources include:

```text
Deployment/kubelet-csr-approver
ServiceAccount/kubelet-csr-approver
ClusterRole/kubelet-csr-approver
ClusterRoleBinding/kubelet-csr-approver
```

At the last inspection:

```bash
kubectl get csr
```

returned no active CSR objects.

This is not an error. Serving CSR objects are created as needed by kubelet certificate bootstrap/rotation.

---

## 4. Security policy currently in force

### 4.1 Hostname restriction

Current:

```yaml
providerRegex: '^ubuntu-24-04-(mgmt|wrk)-0[1-3]$'
```

This restricts valid CSR DNS names to the six expected production node naming patterns.

Expected nodes:

```text
ubuntu-24-04-mgmt-01
ubuntu-24-04-mgmt-02
ubuntu-24-04-mgmt-03
ubuntu-24-04-wrk-01
ubuntu-24-04-wrk-02
ubuntu-24-04-wrk-03
```

Do not broaden this regex without a security review.

Bad example:

```yaml
providerRegex: '.*'
```

---

### 4.2 IP restriction

Current:

```yaml
providerIpPrefixes: >-
  172.16.6.20/32,
  172.16.6.21/32,
  172.16.6.22/32,
  172.16.6.23/32,
  172.16.6.24/32,
  172.16.6.25/32
```

The `/32` policy is intentionally strict.

It restricts approved serving certificate IP SANs to the known node IP addresses.

Do not replace this with an entire subnet such as:

```text
172.16.6.0/24
```

unless new operational requirements justify the increased trust scope.

---

### 4.3 DNS validation

Keep:

```yaml
bypassDnsResolution: false
```

The upstream project explicitly states that DNS resolution is part of its validation model.

Setting this to `true` disables an important validation layer.

---

### 4.4 Hostname validation

Keep:

```yaml
bypassHostnameCheck: false
```

The controller verifies that the requested DNS name corresponds to the node identity.

Do not bypass this in production without a documented exception.

---

### 4.5 Approval behavior

The controller validates items including:

- signerName;
- CSR username;
- x509 Common Name;
- DNS SAN count;
- requested DNS names;
- requested IP SANs;
- provider regex;
- provider IP prefixes;
- DNS resolution;
- hostname relationship;
- requested certificate expiration.

The upstream project explicitly describes an attacker model in which incorrect approval could lead to forged serving certificates.

Official reference:

https://github.com/postfinance/kubelet-csr-approver

---

## 5. Production GitOps architecture

```text
                         GitHub
                           |
                           | main
                           v
                    gitops-platform
                           |
                           v
                        Argo CD
                           |
                           v
                Application
                kubelet-csr-approver
                           |
                 +---------+---------+
                 |                   |
                 v                   v
         Official Helm repo       Git values
         chart 1.1.0              values.yaml
                 |                   |
                 +---------+---------+
                           |
                           v
                     kube-system
                           |
       +-------------------+--------------------+
       |                   |                    |
       v                   v                    v
   Deployment       ServiceAccount        ClusterRole
     2 replicas            |                    |
       |                   |                    v
       |                   +----------> ClusterRoleBinding
       |
       +--> leader election
       +--> metrics :8080
       +--> watches CSR API
       +--> validates kubelet-serving CSRs
       +--> approves/denies according to policy
```

### Core principle

```text
Git controls desired state
        |
        v
Argo CD controls lifecycle
        |
        v
Helm only renders the chart
```

After migration, do not use `helm upgrade` for normal production changes.

---

## 6. Why no extra raw-resource directory is required initially

For Headlamp, separate Git resources were useful for Ingress, Certificate and custom RBAC.

For `kubelet-csr-approver`, the official Helm chart already manages:

- Deployment
- ServiceAccount
- RBAC
- ClusterRole
- ClusterRoleBinding
- metrics Service
- security context
- leader election configuration

Therefore the initial production adoption should use only:

```text
applications/kubelet-csr-approver.yaml
helm-values/kubelet-csr-approver/values.yaml
```

Do not duplicate chart-owned RBAC in a separate raw manifest.

Duplicating ownership increases the chance of Argo CD conflicts and configuration drift.

---

## 7. Repository structure

Recommended:

```text
gitops-platform/
├── clusters/
│   └── production/
│       └── argocd/
│           ├── applications/
│           │   ├── headlamp.yaml
│           │   └── kubelet-csr-approver.yaml
│           └── projects/
│               └── platform-project.yaml
└── helm-values/
    ├── headlamp/
    │   └── values.yaml
    └── kubelet-csr-approver/
        └── values.yaml
```

Do not deploy `values-computed.yaml`.

Computed values may be retained outside the deployment path for historical auditing, but they should not become the desired configuration.

---

## 8. Production `values.yaml`

Path:

```text
helm-values/kubelet-csr-approver/values.yaml
```

### Adoption profile

```yaml
# -----------------------------------------------------------------------------
# CSR validation policy
# -----------------------------------------------------------------------------

providerRegex: '^ubuntu-24-04-(mgmt|wrk)-0[1-3]$'

providerIpPrefixes: >-
  172.16.6.20/32,
  172.16.6.21/32,
  172.16.6.22/32,
  172.16.6.23/32,
  172.16.6.24/32,
  172.16.6.25/32

bypassDnsResolution: false
bypassHostnameCheck: false

# Keep current chart behavior during adoption.
allowedDnsNames: 1
ignoreNonSystemNode: false

# Do not change certificate lifetime during GitOps adoption.
maxExpirationSeconds: ""

# -----------------------------------------------------------------------------
# Availability
# -----------------------------------------------------------------------------

replicas: 2
leaderElection: true

# -----------------------------------------------------------------------------
# RBAC / identity
# -----------------------------------------------------------------------------

rbac:
  manage: true

serviceAccount:
  create: true
  name: ""

# -----------------------------------------------------------------------------
# Metrics
# -----------------------------------------------------------------------------

metrics:
  enable: true
  port: 8080
  serviceType: ClusterIP

  # Keep current behavior during adoption.
  # Integrate with kube-prometheus-stack only in a separate change.
  serviceMonitor:
    enabled: false

# -----------------------------------------------------------------------------
# Resources
# -----------------------------------------------------------------------------

resources:
  requests:
    cpu: 100m
    memory: 64Mi
  limits:
    cpu: 500m
    memory: 128Mi

# -----------------------------------------------------------------------------
# Container security
# -----------------------------------------------------------------------------

securityContext:
  allowPrivilegeEscalation: false
  capabilities:
    drop:
      - all
  privileged: false
  readOnlyRootFilesystem: true
  runAsGroup: 65532
  runAsNonRoot: true
  runAsUser: 65532
  seccompProfile:
    type: RuntimeDefault

# -----------------------------------------------------------------------------
# Scheduling
# -----------------------------------------------------------------------------

tolerations:
  - effect: NoSchedule
    key: node-role.kubernetes.io/control-plane
    operator: Equal
```

### Why this is more explicit than the existing user-supplied values

The existing release only overrides four values. For production GitOps, this file intentionally pins the **security-, availability-, resource-, and identity-critical behavior** currently observed from chart `1.1.0`.

This makes the intended production profile readable without copying every chart default.

Do not copy the entire computed values file.

---

## 9. Argo CD Application

Path:

```text
clusters/production/argocd/applications/kubelet-csr-approver.yaml
```

### Phase A — initial adoption

Use manual sync first:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: kubelet-csr-approver
  namespace: argocd
spec:
  project: platform

  sources:
    # Official upstream chart.
    - repoURL: https://postfinance.github.io/kubelet-csr-approver
      chart: kubelet-csr-approver
      targetRevision: 1.1.0
      helm:
        releaseName: kubelet-csr-approver
        valueFiles:
          - $values/helm-values/kubelet-csr-approver/values.yaml

    # Git repository containing production values.
    - repoURL: https://github.com/SattyaPiseth/gitops-platform.git
      targetRevision: main
      ref: values

  destination:
    server: https://kubernetes.default.svc
    namespace: kube-system

  syncPolicy:
    syncOptions:
      - CreateNamespace=false
      - ApplyOutOfSyncOnly=true
```

### Why `CreateNamespace=false`

`kube-system` is a core Kubernetes namespace and already exists.

Argo CD must not own or attempt to create it as part of this application.

---

## 10. AppProject integration

The existing `platform` AppProject already needs:

```yaml
sourceRepos:
  - https://postfinance.github.io/kubelet-csr-approver
  - https://github.com/SattyaPiseth/gitops-platform.git
```

and:

```yaml
destinations:
  - server: https://kubernetes.default.svc
    namespace: kube-system
```

Those are the key requirements for this Application.

Because the chart creates cluster-scoped RBAC resources, the AppProject must also permit the required cluster-scoped kinds.

The current shared platform project broadly allows cluster resources.

### Security observation

A shared project with:

```yaml
clusterResourceWhitelist:
  - group: "*"
    kind: "*"
```

is highly privileged.

That may be operationally necessary for your platform components, but Git write access and Argo CD project access must therefore be treated as production-administrator access.

Future project hardening should be done separately from this migration.

---

## 11. Do not upgrade during migration

Current:

```text
Chart:       1.1.0
App version: v1.1.0
```

Upstream currently has newer releases.

That does **not** mean this migration should upgrade the chart.

Required sequence:

```text
Phase A
Helm-managed 1.1.0
      |
      v
Argo-managed 1.1.0
```

Only after stable adoption:

```text
Phase B
Review upstream release notes
      |
      v
Test newer version
      |
      v
Upgrade through Git
```

Combining lifecycle-controller migration with a chart upgrade makes rollback and fault attribution significantly harder.

Official releases:

https://github.com/postfinance/kubelet-csr-approver/releases

---

## 12. Pre-migration baseline

Capture the live state before committing the Argo CD Application.

### Helm

```bash
helm get values kubelet-csr-approver -n kube-system

helm get values kubelet-csr-approver -n kube-system -a

helm get manifest kubelet-csr-approver   -n kube-system   > /tmp/kubelet-csr-approver-live.yaml

helm get metadata kubelet-csr-approver -n kube-system

helm history kubelet-csr-approver -n kube-system
```

### Kubernetes resources

```bash
kubectl get deployment kubelet-csr-approver   -n kube-system -o yaml   > /tmp/kubelet-csr-approver-deployment-live.yaml

kubectl get serviceaccount kubelet-csr-approver   -n kube-system -o yaml   > /tmp/kubelet-csr-approver-sa-live.yaml

kubectl get clusterrole kubelet-csr-approver -o yaml   > /tmp/kubelet-csr-approver-clusterrole-live.yaml

kubectl get clusterrolebinding kubelet-csr-approver -o yaml   > /tmp/kubelet-csr-approver-clusterrolebinding-live.yaml
```

### Runtime arguments / environment

```bash
kubectl get deployment kubelet-csr-approver   -n kube-system   -o jsonpath='{.spec.template.spec.containers[0].args}'
echo

kubectl get deployment kubelet-csr-approver   -n kube-system   -o jsonpath='{.spec.template.spec.containers[0].env}'
echo
```

### Health

```bash
kubectl get pods -n kube-system   -l app.kubernetes.io/name=kubelet-csr-approver   -o wide

kubectl logs -n kube-system   deployment/kubelet-csr-approver   --tail=200
```

### CSR state

```bash
kubectl get csr
```

---

## 13. Verify kubelet TLS bootstrap

The controller is useful only when kubelets request serving certificates.

Upstream quick-start requires:

```yaml
serverTLSBootstrap: true
```

in kubelet configuration.

Verify on each node:

```bash
grep -n '^serverTLSBootstrap:' /var/lib/kubelet/config.yaml
```

Expected:

```text
serverTLSBootstrap: true
```

For the six-node cluster, verify all nodes.

Do not modify kubelet configuration as part of Argo CD adoption if it is already working.

---

## 14. Validate DNS assumptions

Because:

```yaml
bypassDnsResolution: false
```

the controller expects node DNS names to resolve correctly.

Verify all expected node names:

```bash
getent hosts ubuntu-24-04-mgmt-01
getent hosts ubuntu-24-04-mgmt-02
getent hosts ubuntu-24-04-mgmt-03
getent hosts ubuntu-24-04-wrk-01
getent hosts ubuntu-24-04-wrk-02
getent hosts ubuntu-24-04-wrk-03
```

The results must correspond to the IPs permitted by `providerIpPrefixes`.

DNS is part of the controller's security model.

---

## 15. Local Helm rendering

Before Argo CD adoption:

```bash
cd /opt/gitops-platform

helm repo add kubelet-csr-approver   https://postfinance.github.io/kubelet-csr-approver

helm repo update
```

Render:

```bash
helm template kubelet-csr-approver   kubelet-csr-approver/kubelet-csr-approver   --version 1.1.0   --namespace kube-system   -f helm-values/kubelet-csr-approver/values.yaml   > /tmp/kubelet-csr-approver-gitops.yaml
```

---

## 16. Compare rendered and existing manifests

Do not rely only on a raw `diff`; Kubernetes live resources contain generated fields.

At minimum compare these areas:

- resource names;
- image;
- replicas;
- ServiceAccount;
- ClusterRole rules;
- ClusterRoleBinding subject;
- container arguments/environment;
- resource requests/limits;
- securityContext;
- tolerations;
- metrics Service;
- leader election settings.

Useful commands:

```bash
grep -nE '^kind:|^  name:|image:|replicas:|serviceAccountName:'   /tmp/kubelet-csr-approver-live.yaml

grep -nE '^kind:|^  name:|image:|replicas:|serviceAccountName:'   /tmp/kubelet-csr-approver-gitops.yaml
```

Inspect RBAC separately.

---

## 17. RBAC validation

The controller needs permission to observe and approve/deny CSRs.

Kubernetes documents CSR approval as a privileged action involving:

- read access to CertificateSigningRequests;
- update access to `certificatesigningrequests/approval`;
- approval authorization for the requested signer.

The upstream chart provides the required RBAC.

Do not manually broaden the chart's ClusterRole.

Verify:

```bash
kubectl get clusterrole kubelet-csr-approver -o yaml
```

and compare with the rendered Helm chart.

Official Kubernetes reference:

https://kubernetes.io/docs/reference/access-authn-authz/certificate-signing-requests/

---

## 18. Git validation and commit

```bash
cd /opt/gitops-platform

git status
git diff --check
git diff
```

Stage:

```bash
git add   helm-values/kubelet-csr-approver/values.yaml   clusters/production/argocd/applications/kubelet-csr-approver.yaml
```

Review:

```bash
git diff --cached
```

Commit:

```bash
git commit -m "feat(gitops): adopt kubelet-csr-approver"
git push origin main
```

---

## 19. Bootstrap the Argo CD Application

If the Application does not yet exist:

```bash
kubectl apply   -f clusters/production/argocd/applications/kubelet-csr-approver.yaml
```

This is the bootstrap step.

Do not immediately enable automatic sync.

Inspect:

```bash
kubectl get application kubelet-csr-approver -n argocd
kubectl describe application kubelet-csr-approver -n argocd
```

Expected before first sync may be:

```text
OutOfSync / Healthy
```

---

## 20. Review Argo CD diff before first sync

Use the Argo CD UI or CLI:

```bash
argocd app diff kubelet-csr-approver
```

Review any change involving:

```text
ClusterRole
ClusterRoleBinding
ServiceAccount
Deployment
Service
container args
providerRegex
providerIpPrefixes
```

Do not sync if Argo CD proposes unexpected deletion or broad RBAC modification.

---

## 21. First sync

Perform the first synchronization manually.

CLI:

```bash
argocd app sync kubelet-csr-approver
```

or use the Argo CD UI.

Then:

```bash
kubectl get application kubelet-csr-approver -n argocd
```

Target:

```text
Synced / Healthy
```

---

## 22. Post-adoption validation

### Deployment

```bash
kubectl get deployment kubelet-csr-approver -n kube-system
```

Expected:

```text
READY 2/2
```

### Pods

```bash
kubectl get pods -n kube-system   -l app.kubernetes.io/name=kubelet-csr-approver   -o wide
```

### Logs

```bash
kubectl logs -n kube-system   deployment/kubelet-csr-approver   --tail=200
```

Look for:

- startup errors;
- invalid configuration;
- DNS validation failures;
- RBAC/Forbidden errors;
- leader-election errors;
- unexpected CSR denial/approval activity.

### RBAC

```bash
kubectl get clusterrole kubelet-csr-approver
kubectl get clusterrolebinding kubelet-csr-approver
```

### ServiceAccount

```bash
kubectl get sa kubelet-csr-approver -n kube-system
```

### Metrics

```bash
kubectl get svc -n kube-system | grep kubelet-csr-approver
```

If available, inspect the Service:

```bash
kubectl describe svc kubelet-csr-approver -n kube-system
```

### CSR state

```bash
kubectl get csr
```

---

## 23. Validate CSR policy when a request appears

When a serving CSR appears:

```bash
kubectl get csr
```

Inspect:

```bash
kubectl get csr <CSR_NAME> -o yaml
```

Verify:

```text
spec.signerName = kubernetes.io/kubelet-serving
spec.username   = system:node:<expected-node>
```

Review SANs:

```bash
kubectl get csr <CSR_NAME>   -o jsonpath='{.spec.request}' |
base64 -d |
openssl req -text -noout
```

The DNS/IP SANs must match the production node inventory and validation policy.

Do not manually approve a failed CSR merely to make it work until the validation failure has been explained.

---

## 24. Enable automatic GitOps reconciliation only after stable adoption

After the manual sync has been verified, update the Application through Git:

```yaml
syncPolicy:
  automated:
    enabled: true
    prune: true
    selfHeal: true
  syncOptions:
    - CreateNamespace=false
    - ApplyOutOfSyncOnly=true
```

Commit:

```bash
git add clusters/production/argocd/applications/kubelet-csr-approver.yaml
git commit -m "chore(gitops): enable kubelet-csr-approver auto sync"
git push origin main
```

### Why delayed automation

This provides a controlled cutover:

```text
Manual Helm
   |
   v
Argo CD manual adoption
   |
   v
Verification
   |
   v
Automated GitOps
```

This is safer for a certificate-approval controller than immediately enabling prune/self-heal before validating the generated state.

---

## 25. Helm ownership after migration

Argo CD uses Helm as a template engine; it does not use Helm as the application lifecycle controller.

After cutover:

```text
Git + Argo CD = owner
```

Do not run:

```bash
helm upgrade kubelet-csr-approver ...
helm rollback kubelet-csr-approver ...
helm uninstall kubelet-csr-approver ...
```

against the Argo-managed workload.

### Existing Helm release metadata

The historical Helm release records may remain visible through:

```bash
helm list -A
```

until Helm release metadata is explicitly retired.

Do **not** run `helm uninstall` to remove that history after Argo CD adoption because Helm would attempt to delete the Kubernetes resources.

If you decide to retire Helm release metadata, treat it as a separate controlled cleanup procedure:

1. back up Helm release metadata;
2. verify Argo CD owns and has synchronized every resource;
3. identify Helm release Secrets for this release only;
4. remove only the historical release records;
5. verify Argo CD remains `Synced / Healthy`.

This cleanup is optional and should not be mixed with the initial adoption.

---

## 26. Monitoring integration with kube-prometheus-stack

Current:

```yaml
metrics:
  enable: true
  serviceMonitor:
    enabled: false
```

The metrics endpoint is already enabled, but a `ServiceMonitor` is not currently created.

### Adoption recommendation

Keep:

```yaml
serviceMonitor:
  enabled: false
```

during GitOps migration.

Do not change monitoring behavior during controller adoption.

### Phase 2 recommendation

After migration, inspect the current Prometheus Operator selectors:

```bash
kubectl get prometheus -n monitoring -o yaml
```

Review:

```text
serviceMonitorSelector
serviceMonitorNamespaceSelector
```

Then, if compatible, enable:

```yaml
metrics:
  serviceMonitor:
    enabled: true
    interval: 1m
    scrapeTimeout: 10s
```

Potential labels may be required depending on your `kube-prometheus-stack` configuration.

This must be a separate Git commit and validation step.

---

## 27. `maxExpirationSeconds` hardening

Current:

```yaml
maxExpirationSeconds: ""
```

Upstream has a hard maximum of 367 days and allows administrators to reduce it.

Do not change this during adoption.

### Later hardening

Consider an explicit lifetime only after validating kubelet rotation behavior and cluster signing configuration.

Example candidate:

```yaml
maxExpirationSeconds: "2592000"
```

for approximately 30 days.

This is **not** part of the initial migration recommendation.

---

## 28. Upgrade strategy

Current chart:

```text
1.1.0
```

Upstream has newer releases.

Upgrade is a separate project.

Required upgrade workflow:

```text
1. Review upstream release notes.
2. Review chart values/schema changes.
3. Review Kubernetes compatibility.
4. Render new chart locally.
5. Diff RBAC.
6. Diff container args.
7. Test in non-production if available.
8. Commit chart version change.
9. Manual production sync.
10. Observe CSR behavior.
11. Re-enable/retain automation.
```

Never combine:

```text
GitOps adoption + chart upgrade + security-policy change
```

in one change.

---

## 29. Rollback

### Before automated sync is enabled

If the first Argo sync introduces an issue, revert the Git commit / Application and restore the prior known state according to the captured baseline.

### After GitOps ownership is established

Prefer Git revert:

```bash
git log --oneline

git revert <BAD_COMMIT>

git push origin main
```

Argo CD reconciles to the reverted desired state.

Do not use Helm rollback for an Argo-managed application.

---

## 30. Change-management rules

### Allowed normal workflow

```text
edit Git
   |
   v
review
   |
   v
commit
   |
   v
push
   |
   v
Argo CD
   |
   v
Kubernetes
```

### Avoid during normal operations

```text
helm upgrade
helm rollback
helm uninstall
kubectl edit deployment
kubectl edit clusterrole
kubectl patch clusterrolebinding
kubectl set image
manual CSR approval without investigation
```

Emergency changes must be documented and immediately reconciled into Git.

---

## 31. Production verification checklist

### Before migration

- [ ] Current release version captured.
- [ ] User-supplied values captured.
- [ ] Computed values captured.
- [ ] Current manifest captured.
- [ ] Deployment captured.
- [ ] ClusterRole captured.
- [ ] ClusterRoleBinding captured.
- [ ] Runtime args/env captured.
- [ ] `serverTLSBootstrap=true` verified on all nodes.
- [ ] Node DNS resolves correctly.
- [ ] `providerRegex` matches only expected nodes.
- [ ] `providerIpPrefixes` contains only expected node IPs.
- [ ] Current logs healthy.
- [ ] Current CSR state reviewed.

### Before first Argo sync

- [ ] Chart pinned to `1.1.0`.
- [ ] No version upgrade.
- [ ] Values render successfully.
- [ ] Rendered RBAC reviewed.
- [ ] Rendered Deployment reviewed.
- [ ] Rendered securityContext reviewed.
- [ ] Argo CD diff reviewed.
- [ ] No unexpected deletes.
- [ ] No unexpected RBAC expansion.

### After first sync

- [ ] Application `Synced / Healthy`.
- [ ] Deployment `2/2`.
- [ ] Both pods healthy.
- [ ] Leader election healthy.
- [ ] ServiceAccount unchanged.
- [ ] ClusterRole behavior unchanged.
- [ ] ClusterRoleBinding behavior unchanged.
- [ ] Metrics Service healthy.
- [ ] No `Forbidden` errors.
- [ ] No DNS validation errors.
- [ ] No unexpected CSR approval.
- [ ] No unexpected CSR denial.

### Before enabling automated sync

- [ ] Stable adoption confirmed.
- [ ] Git is authoritative.
- [ ] Operations team instructed not to use Helm.
- [ ] Rollback procedure documented.
- [ ] Argo alerts/monitoring available.

---

## 32. Documentation maintenance standard

Every production component document should contain:

1. **Purpose**
2. **Security impact**
3. **Architecture**
4. **Current pinned versions**
5. **Repository locations**
6. **Production values**
7. **Dependencies**
8. **RBAC model**
9. **Networking**
10. **Monitoring**
11. **Pre-flight checks**
12. **Deployment/adoption**
13. **Post-deployment validation**
14. **Failure modes**
15. **Rollback**
16. **Upgrade policy**
17. **Change-management rules**
18. **Production checklist**
19. **Official references**
20. **Last reviewed date / owner**

Avoid documentation that consists only of copied commands without explaining why they exist.

---

## 33. Suggested document header convention

Use:

```markdown
# Component Name — Production GitOps Guide

> **Environment:** production
> **Owner:** Platform / DevOps
> **GitOps controller:** Argo CD
> **Namespace:** ...
> **Chart:** ...
> **App version:** ...
> **Last reviewed:** YYYY-MM-DD
```

Keep operational commands close to the architectural reason they support.

---

## 34. Official resources

### kubelet-csr-approver

Project / security model / parameters:

https://github.com/postfinance/kubelet-csr-approver

Releases:

https://github.com/postfinance/kubelet-csr-approver/releases

Helm repository:

https://postfinance.github.io/kubelet-csr-approver

### Kubernetes

CertificateSigningRequest API:

https://kubernetes.io/docs/reference/kubernetes-api/certificates/certificate-signing-request-v1/

Certificates and CSR:

https://kubernetes.io/docs/reference/access-authn-authz/certificate-signing-requests/

Certificate approval command:

https://kubernetes.io/docs/reference/kubectl/generated/kubectl_certificate/kubectl_certificate_approve/

### Argo CD

Helm:

https://argo-cd.readthedocs.io/en/latest/user-guide/helm/

Multiple sources:

https://argo-cd.readthedocs.io/en/stable/user-guide/multiple_sources/

Automated sync:

https://argo-cd.readthedocs.io/en/stable/user-guide/auto_sync/

Sync options:

https://argo-cd.readthedocs.io/en/latest/user-guide/sync-options/

Projects:

https://argo-cd.readthedocs.io/en/latest/user-guide/projects/

---

## 35. Final conclusion

The production goal is:

```text
Strict CSR validation policy
        +
Pinned chart version
        +
Git-controlled configuration
        +
Argo CD lifecycle ownership
        +
Chart-managed minimum required RBAC
        +
Hardened container security context
        +
HA with leader election
        +
Controlled node hostname/IP trust boundaries
        +
Observable migration
        +
No simultaneous upgrade
```

The controller's most important security boundaries are not ingress or TLS termination; they are:

```text
providerRegex
providerIpPrefixes
DNS validation
hostname validation
CSR approval RBAC
signer validation
certificate lifetime
```

For the current production cluster, the existing strict node regex and exact `/32` IP list are strong controls and should be preserved unchanged during GitOps adoption.

The safest migration path is:

```text
Existing Helm 1.1.0
        |
        v
Argo CD 1.1.0 manual adoption
        |
        v
Verify CSR policy / RBAC / health
        |
        v
Enable automated prune + self-heal
        |
        v
Later: monitoring hardening
        |
        v
Later: version upgrade
```

This produces a clear, auditable, maintainable GitOps ownership model without changing the certificate-approval behavior at the same time as the migration.

# Headlamp Production Architecture and GitOps Operations Guide

> **Status:** Recommended production baseline  
> **Scope:** In-cluster Headlamp, Argo CD, Helm, cert-manager, Traefik, Kubernetes RBAC  
> **Host:** `headlamp.k8s.tss.local`  
> **TLS issuer:** `ClusterIssuer/k8s-internal-ca`  
> **GitOps repository:** `https://github.com/SattyaPiseth/gitops-platform.git`  
> **Headlamp chart:** `headlamp/headlamp` `0.43.0`

---

## 1. Purpose

This document defines a production baseline for running Headlamp as a secure, read-only Kubernetes dashboard managed through GitOps.

The architecture has five goals:

1. Git is the source of truth for Headlamp configuration.
2. Argo CD owns the application lifecycle; Helm is used only to render the chart.
3. Headlamp does not receive `cluster-admin`.
4. Users authenticate with a dedicated read-only identity, not the Headlamp runtime ServiceAccount.
5. TLS is terminated by Traefik using a cert-manager-managed certificate for `headlamp.k8s.tss.local`.

---

## 2. Verified design principles

### 2.1 Headlamp authentication and authorization

Headlamp supports bearer-token authentication and recommends a Kubernetes ServiceAccount token as a login method. Kubernetes RBAC determines what that identity can access.

The Headlamp Helm chart also has an in-cluster runtime ServiceAccount. These are separate concerns:

```text
Headlamp Pod
  |
  +-- runs as: headlamp/headlamp
  |
  +-- does NOT represent every user
      unless unsafeUseServiceAccountToken=true

Browser User
  |
  +-- logs in using token/OIDC
  |
  +-- Kubernetes RBAC evaluates that user identity
```

**Production rule:** keep `config.unsafeUseServiceAccountToken: false`.

Do not use the runtime ServiceAccount as a shared human credential.

Official references:

- https://headlamp.dev/docs/latest/installation/
- https://headlamp.dev/docs/latest/installation/in-cluster/
- https://github.com/kubernetes-sigs/headlamp/blob/main/charts/headlamp/README.md

---

### 2.2 Headlamp chart RBAC

Headlamp chart `0.43.0` defaults to:

```yaml
clusterRoleBinding:
  create: true
  clusterRoleName: cluster-admin
```

For this production architecture this must be disabled:

```yaml
clusterRoleBinding:
  create: false
```

Do **not** use:

```yaml
clusterRoleBinding:
  enabled: false
```

`enabled` is not the documented chart key.

---

### 2.3 Kubernetes least privilege

Kubernetes recommends:

- minimal RBAC rights;
- application-specific ServiceAccounts;
- avoiding `cluster-admin` except where explicitly required;
- avoiding wildcard resource permissions when practical;
- minimizing distribution of privileged tokens;
- avoiding Secret read access in read-only roles unless required.

Official references:

- https://kubernetes.io/docs/concepts/security/rbac-good-practices/
- https://kubernetes.io/docs/reference/access-authn-authz/rbac/
- https://kubernetes.io/docs/concepts/security/service-accounts/

---

### 2.4 Argo CD and Helm

Argo CD does not use Helm as the lifecycle controller. Argo CD uses Helm to inflate/render the chart and then Argo CD manages the resulting Kubernetes objects.

External Helm charts can use Git-hosted value files through Argo CD multiple sources and `$values`.

Official references:

- https://argo-cd.readthedocs.io/en/latest/user-guide/helm/
- https://argo-cd.readthedocs.io/en/stable/user-guide/multiple_sources/
- https://argo-cd.readthedocs.io/en/stable/user-guide/auto_sync/
- https://argo-cd.readthedocs.io/en/latest/user-guide/sync-options/

---

### 2.5 TLS

TLS terminates at Traefik.

```text
Browser
  |
  | HTTPS :443
  v
Traefik
  |
  | TLS Secret: headlamp-tls
  v
Ingress
  |
  | HTTP
  v
Service/headlamp :80
  |
  v
Headlamp Pods
```

Headlamp backend TLS is not required for this ingress-termination architecture.

cert-manager manages `Secret/headlamp-tls` from `Certificate/headlamp-tls` and renews the certificate.

Official references:

- https://cert-manager.io/docs/usage/certificate/
- https://cert-manager.io/docs/configuration/
- https://doc.traefik.io/traefik/master/reference/routing-configuration/kubernetes/ingress/
- https://headlamp.dev/docs/latest/installation/in-cluster/

---

## 3. Final production architecture

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
                 +--------------+--------------+
                 |                             |
                 v                             v
        Official Headlamp Helm             Git source
             chart 0.43.0                      |
                 |                 +------------+------------+
                 |                 |            |            |
                 |                 v            v            v
                 |              values      resources     TLS/RBAC
                 |                 |            |            |
                 +-----------------+------------+------------+
                                   |
                                   v
                         Namespace/headlamp
                                   |
                 +-----------------+------------------+
                 |                 |                  |
                 v                 v                  v
            Deployment          Service           Ingress
            Headlamp x3         ClusterIP          Traefik
                 |                                    |
                 |                               headlamp-tls
                 |                                    |
                 |                                    v
                 |                          headlamp.k8s.tss.local
                 |
                 v
        ServiceAccount/headlamp
        (runtime identity only)

Browser user
     |
     | short-lived bearer token
     v
ServiceAccount/headlamp-viewer
     |
     v
ClusterRoleBinding/headlamp-platform-viewer
     |
     v
ClusterRole/headlamp-platform-view
     |
     +-- get/list/watch Kubernetes resources
     +-- get/list/watch metrics.k8s.io
     +-- no Secrets
     +-- no create/update/patch/delete
```

---

## 4. Recommended repository layout

```text
gitops-platform/
├── clusters/
│   └── production/
│       └── argocd/
│           ├── applications/
│           │   └── headlamp.yaml
│           ├── projects/
│           │   └── platform-project.yaml
│           └── resources/
│               └── headlamp/
│                   ├── namespace.yaml
│                   ├── certificate.yaml
│                   ├── ingress.yaml
│                   └── rbac.yaml
└── helm-values/
    └── headlamp/
        └── values.yaml
```

Do not retain `values-computed.yaml` as a deployment source. Computed values are useful only for diagnostics or migration auditing.

---

## 5. Helm values

Path:

```text
helm-values/headlamp/values.yaml
```

Recommended:

```yaml
replicaCount: 3

config:
  inCluster: true
  pluginsDir: /headlamp/plugins
  unsafeUseServiceAccountToken: false

serviceAccount:
  create: true
  name: headlamp

clusterRoleBinding:
  create: false

service:
  type: ClusterIP
  port: 80

ingress:
  enabled: false

resources:
  requests:
    cpu: 100m
    memory: 128Mi
  limits:
    cpu: 500m
    memory: 512Mi
```

### Why

- `replicaCount: 3`: HA-oriented deployment.
- `inCluster: true`: official in-cluster mode.
- `unsafeUseServiceAccountToken: false`: prevents all users from silently becoming the pod ServiceAccount.
- `serviceAccount.name: headlamp`: deterministic runtime identity.
- `clusterRoleBinding.create: false`: prevents default `cluster-admin` binding.
- `ClusterIP`: Traefik is the external entry point.
- Helm ingress disabled because Ingress and Certificate are maintained as explicit Git resources.

---

## 6. Namespace

Path:

```text
clusters/production/argocd/resources/headlamp/namespace.yaml
```

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: headlamp
  labels:
    app.kubernetes.io/part-of: platform
    app.kubernetes.io/managed-by: argocd
```

The Application uses:

```yaml
syncOptions:
  - CreateNamespace=false
```

because the Namespace itself is declared in Git.

An alternative design is to omit `namespace.yaml` and use `CreateNamespace=true`. Do not use both approaches without a reason.

---

## 7. Read-only login RBAC

Path:

```text
clusters/production/argocd/resources/headlamp/rbac.yaml
```

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: headlamp-viewer
  namespace: headlamp
automountServiceAccountToken: false

---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: headlamp-platform-view
rules:
  # Core
  - apiGroups: [""]
    resources:
      - pods
      - pods/log
      - services
      - endpoints
      - endpointslices
      - configmaps
      - namespaces
      - nodes
      - persistentvolumes
      - persistentvolumeclaims
      - replicationcontrollers
      - resourcequotas
      - limitranges
      - events
    verbs: ["get", "list", "watch"]

  # Workloads
  - apiGroups: ["apps"]
    resources:
      - deployments
      - replicasets
      - statefulsets
      - daemonsets
    verbs: ["get", "list", "watch"]

  # Batch
  - apiGroups: ["batch"]
    resources:
      - jobs
      - cronjobs
    verbs: ["get", "list", "watch"]

  # Networking
  - apiGroups: ["networking.k8s.io"]
    resources:
      - ingresses
      - ingressclasses
      - networkpolicies
    verbs: ["get", "list", "watch"]

  # Storage
  - apiGroups: ["storage.k8s.io"]
    resources:
      - storageclasses
      - volumeattachments
      - csidrivers
      - csinodes
    verbs: ["get", "list", "watch"]

  # Metrics API
  - apiGroups: ["metrics.k8s.io"]
    resources:
      - nodes
      - pods
    verbs: ["get", "list", "watch"]

  # CRD discovery
  - apiGroups: ["apiextensions.k8s.io"]
    resources:
      - customresourcedefinitions
    verbs: ["get", "list", "watch"]

---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: headlamp-platform-viewer
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: headlamp-platform-view
subjects:
  - kind: ServiceAccount
    name: headlamp-viewer
    namespace: headlamp
```

### Security characteristics

Expected:

```text
Read Pods                 yes
Read Nodes                yes
Read Deployments          yes
Read node metrics         yes
Read pod metrics          yes
Read Secrets              no
Create Deployment         no
Delete Pod                no
Patch Namespace           no
Bind RBAC                 no
Escalate RBAC             no
```

Do not add Secrets to this role unless there is a reviewed requirement. Kubernetes explicitly warns that reading Secrets can expose credentials and enable privilege escalation.

---

## 8. Certificate

Path:

```text
clusters/production/argocd/resources/headlamp/certificate.yaml
```

```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: headlamp-tls
  namespace: headlamp
spec:
  secretName: headlamp-tls
  dnsNames:
    - headlamp.k8s.tss.local
  issuerRef:
    name: k8s-internal-ca
    kind: ClusterIssuer
    group: cert-manager.io
```

### Critical invariant

These values must match:

```text
Certificate.spec.dnsNames
Ingress.spec.tls.hosts
Ingress.spec.rules.host
DNS record
```

All must use:

```text
headlamp.k8s.tss.local
```

The previous `headlamp.tss.local` certificate name was inconsistent and should not be used.

---

## 9. Ingress

Path:

```text
clusters/production/argocd/resources/headlamp/ingress.yaml
```

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: headlamp
  namespace: headlamp
  labels:
    app.kubernetes.io/name: headlamp
    app.kubernetes.io/instance: headlamp
spec:
  ingressClassName: traefik

  tls:
    - hosts:
        - headlamp.k8s.tss.local
      secretName: headlamp-tls

  rules:
    - host: headlamp.k8s.tss.local
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: headlamp
                port:
                  number: 80
```

No separate TLS Secret manifest is required; cert-manager creates and renews `Secret/headlamp-tls`.

---

## 10. Argo CD Application

Path:

```text
clusters/production/argocd/applications/headlamp.yaml
```

Recommended two-source configuration:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: headlamp
  namespace: argocd
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  project: platform

  sources:
    # Source 1: official Helm chart
    - repoURL: https://kubernetes-sigs.github.io/headlamp/
      chart: headlamp
      targetRevision: 0.43.0
      helm:
        releaseName: headlamp
        valueFiles:
          - $values/helm-values/headlamp/values.yaml

    # Source 2: values + additional Kubernetes resources
    - repoURL: https://github.com/SattyaPiseth/gitops-platform.git
      targetRevision: main
      ref: values
      path: clusters/production/argocd/resources/headlamp

  destination:
    server: https://kubernetes.default.svc
    namespace: headlamp

  syncPolicy:
    automated:
      enabled: true
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=false
      - ApplyOutOfSyncOnly=true
```

### Why two sources

Argo CD documents that a source with `ref` can provide `$values`, and if that same source also has `path`, Argo CD also generates Kubernetes resources from that path.

This is simpler than declaring the same Git repository twice.

Argo CD also warns against using multi-source Applications as a generic grouping mechanism. This architecture has only two cohesive sources: upstream chart + configuration repository.

---

## 11. AppProject

Current shared project:

```text
clusters/production/argocd/projects/platform-project.yaml
```

Your current project explicitly restricts repositories and destinations, which is good.

However, it currently allows:

```yaml
clusterResourceWhitelist:
  - group: "*"
    kind: "*"

namespaceResourceWhitelist:
  - group: "*"
    kind: "*"
```

### Production interpretation

This is a **platform-admin AppProject**, not a least-privilege application project.

Because this project is also intended to manage CNPG, Longhorn, Traefik, monitoring and other platform components, broad cluster-scoped permissions may be operationally necessary.

Treat write access to the Git repository and Argo CD project as privileged administrative access.

Future hardening recommendation:

```text
platform-networking
platform-storage
platform-database
platform-observability
platform-ui
```

with explicit source/destination/resource policies.

Do not tighten the shared project during the Headlamp migration unless all other applications are tested against the new restrictions.

Official reference:

- https://argo-cd.readthedocs.io/en/latest/user-guide/projects/
- https://argo-cd.readthedocs.io/en/stable/operator-manual/project-specification/

---

## 12. GitOps deployment workflow

### 12.1 Pre-flight

```bash
cd /opt/gitops-platform

kubectl get clusterissuer k8s-internal-ca
kubectl get ingressclass
kubectl get svc -n traefik
kubectl get apiservice v1beta1.metrics.k8s.io
kubectl top nodes
```

Expected:

- ClusterIssuer `READY=True`
- Traefik IngressClass exists
- Traefik LoadBalancer reachable
- Metrics API available
- `kubectl top nodes` works

---

### 12.2 Validate YAML

```bash
kubectl apply --dry-run=client \
  -f clusters/production/argocd/resources/headlamp/
```

Validate Application:

```bash
kubectl apply --dry-run=client \
  -f clusters/production/argocd/applications/headlamp.yaml
```

---

### 12.3 Render Helm locally

```bash
helm repo add headlamp https://kubernetes-sigs.github.io/headlamp/
helm repo update

helm template headlamp headlamp/headlamp \
  --version 0.43.0 \
  --namespace headlamp \
  -f helm-values/headlamp/values.yaml \
  > /tmp/headlamp-rendered.yaml
```

Security checks:

```bash
grep -n "cluster-admin" /tmp/headlamp-rendered.yaml
grep -n "headlamp-admin" /tmp/headlamp-rendered.yaml
```

Expected: **no output**.

Confirm runtime ServiceAccount:

```bash
grep -n -A8 "kind: ServiceAccount" /tmp/headlamp-rendered.yaml
```

---

### 12.4 Commit

```bash
git status
git diff --check
git diff

git add \
  helm-values/headlamp/values.yaml \
  clusters/production/argocd/resources/headlamp/ \
  clusters/production/argocd/applications/headlamp.yaml

git diff --cached

git commit -m "feat(headlamp): deploy production read-only dashboard"
git push origin main
```

---

### 12.5 Bootstrap

If the Headlamp Application does not exist yet, the only required bootstrap operation is:

```bash
kubectl apply \
  -f clusters/production/argocd/applications/headlamp.yaml
```

The AppProject must already exist.

After bootstrap, normal changes are made through Git.

---

## 13. Post-deployment verification

### Application

```bash
kubectl get application headlamp -n argocd
```

Expected:

```text
headlamp   Synced   Healthy
```

Detailed:

```bash
kubectl get application headlamp -n argocd \
  -o jsonpath='{.status.sync.status}{" / "}{.status.health.status}{"\n"}'
```

Expected:

```text
Synced / Healthy
```

---

### Workload

```bash
kubectl get pods -n headlamp -o wide
kubectl get deployment headlamp -n headlamp
```

Expected:

```text
READY 3/3
```

---

### Service

```bash
kubectl get svc headlamp -n headlamp
```

Expected:

```text
TYPE: ClusterIP
PORT: 80
```

---

### Certificate

```bash
kubectl get certificate headlamp-tls -n headlamp
```

Expected:

```text
READY=True
SECRET=headlamp-tls
```

Confirm SAN:

```bash
kubectl get certificate headlamp-tls -n headlamp \
  -o jsonpath='{.spec.dnsNames[*]}{"\n"}'
```

Expected:

```text
headlamp.k8s.tss.local
```

---

### Ingress

```bash
kubectl get ingress headlamp -n headlamp
kubectl describe ingress headlamp -n headlamp
```

Expected:

```text
CLASS: traefik
HOST: headlamp.k8s.tss.local
TLS: headlamp-tls
ADDRESS: 172.16.6.200
```

---

### DNS

```bash
getent hosts headlamp.k8s.tss.local
```

Expected:

```text
172.16.6.200
```

---

### HTTPS

```bash
curl -k -I https://headlamp.k8s.tss.local/
```

For a workstation that trusts the internal CA, remove `-k`.

Certificate inspection:

```bash
openssl s_client \
  -connect headlamp.k8s.tss.local:443 \
  -servername headlamp.k8s.tss.local \
  </dev/null 2>/dev/null |
openssl x509 -noout -subject -issuer -dates -ext subjectAltName
```

The SAN must include:

```text
DNS:headlamp.k8s.tss.local
```

---

## 14. Login

Generate a short-lived token for the dedicated viewer account:

```bash
kubectl create token headlamp-viewer \
  -n headlamp \
  --duration=1h
```

Paste that token into the Headlamp login screen.

Do not create a static `kubernetes.io/service-account-token` Secret for normal interactive use.

Official Kubernetes token command:

- https://kubernetes.io/docs/reference/generated/kubectl/kubectl-commands#token

---

## 15. Verify viewer permissions

```bash
SA="system:serviceaccount:headlamp:headlamp-viewer"
```

Expected read permissions:

```bash
kubectl auth can-i list nodes --as="$SA"
kubectl auth can-i list pods -A --as="$SA"
kubectl auth can-i list deployments.apps -A --as="$SA"
kubectl auth can-i list nodes.metrics.k8s.io --as="$SA"
kubectl auth can-i list pods.metrics.k8s.io -A --as="$SA"
```

Expected: `yes`.

Expected denied permissions:

```bash
kubectl auth can-i get secrets -A --as="$SA"
kubectl auth can-i list secrets -A --as="$SA"
kubectl auth can-i create deployments.apps -n default --as="$SA"
kubectl auth can-i delete pods -n default --as="$SA"
kubectl auth can-i patch namespaces --as="$SA"
kubectl auth can-i create clusterrolebindings.rbac.authorization.k8s.io --as="$SA"
```

Expected: `no`.

---

## 16. Verify runtime ServiceAccount is not privileged

```bash
RUNTIME="system:serviceaccount:headlamp:headlamp"

kubectl auth can-i delete pods -A --as="$RUNTIME"
kubectl auth can-i get secrets -A --as="$RUNTIME"
kubectl auth can-i create clusterrolebindings.rbac.authorization.k8s.io --as="$RUNTIME"
```

Expected: `no`.

Also verify there is no legacy binding:

```bash
kubectl get clusterrolebinding -o wide | grep -i headlamp
```

Expected only the viewer binding:

```text
headlamp-platform-viewer  ClusterRole/headlamp-platform-view  headlamp/headlamp-viewer
```

There must be no:

```text
headlamp-admin  ClusterRole/cluster-admin
```

---

## 17. Operational rules

### Allowed

```text
edit Git
  -> review diff
  -> commit
  -> push
  -> Argo CD reconciles
```

### Avoid during normal operations

```text
helm upgrade headlamp ...
kubectl edit deployment headlamp ...
kubectl edit clusterrole ...
kubectl patch application ...
kubectl apply live resources that Argo CD already owns
```

Emergency changes should be documented and immediately reconciled back into Git.

---

## 18. Rollback

Because Argo CD automated sync is enabled, prefer rollback by Git revert:

```bash
git log --oneline
git revert <bad-commit>
git push origin main
```

Argo CD will reconcile the reverted desired state.

Do not rely on `helm rollback`; Argo CD, not Helm, owns the lifecycle.

---

## 19. Production monitoring checklist

Monitor:

- Argo CD Application `Synced` and `Healthy`;
- Headlamp Deployment availability;
- Headlamp pod restarts;
- Traefik route availability;
- cert-manager Certificate readiness and expiration;
- Metrics API availability;
- TLS endpoint response;
- unexpected Headlamp RBAC bindings.

Suggested periodic checks:

```bash
kubectl get application headlamp -n argocd
kubectl get pods -n headlamp
kubectl get certificate headlamp-tls -n headlamp
kubectl get ingress headlamp -n headlamp
kubectl get clusterrolebinding -o wide | grep -i headlamp
```

---

## 20. Production change checklist

Before merge:

- [ ] Chart version pinned.
- [ ] `clusterRoleBinding.create=false`.
- [ ] `unsafeUseServiceAccountToken=false`.
- [ ] No `cluster-admin` in rendered Helm output.
- [ ] Certificate SAN equals Ingress host.
- [ ] Ingress uses `headlamp-tls`.
- [ ] No Secret access in viewer RBAC.
- [ ] No write verbs in viewer RBAC.
- [ ] YAML validates.
- [ ] `helm template` succeeds.
- [ ] Git diff reviewed.

After sync:

- [ ] Argo CD `Synced / Healthy`.
- [ ] 3/3 Headlamp replicas available.
- [ ] Certificate `READY=True`.
- [ ] DNS resolves to Traefik.
- [ ] HTTPS works.
- [ ] Viewer can read resources and metrics.
- [ ] Viewer cannot read Secrets.
- [ ] Viewer cannot create/update/delete.
- [ ] Runtime Headlamp SA has no privileged binding.
- [ ] No legacy `headlamp-admin`.

---

## 21. Current architecture findings

### Correct

- Headlamp chart pinned to `0.43.0`.
- Three replicas.
- `ClusterIP` service.
- Traefik ingress architecture.
- `k8s-internal-ca` ClusterIssuer is healthy.
- cert-manager Certificate model is appropriate.
- Argo CD external Helm values model is appropriate.
- automated prune/self-heal is appropriate for this GitOps-managed component.

### Required corrections

1. Certificate SAN must be:

   ```text
   headlamp.k8s.tss.local
   ```

   not `headlamp.tss.local`.

2. Do not bind `headlamp-platform-view` to runtime `headlamp/headlamp`.

3. Create `headlamp/headlamp-viewer` as the human login identity.

4. Keep:

   ```yaml
   clusterRoleBinding:
     create: false
   ```

5. Explicitly keep:

   ```yaml
   config:
     unsafeUseServiceAccountToken: false
   ```

6. Use two Argo CD sources instead of repeating the Git repository twice.

---

## 22. Security rationale

This architecture limits blast radius in two different compromise scenarios.

### Compromised Headlamp pod

The pod runtime ServiceAccount is not cluster-wide privileged.

```text
Pod compromise
  |
  v
headlamp/headlamp
  |
  +-- no cluster-admin
  +-- no viewer ClusterRole
  +-- no Secret access
```

### Compromised viewer token

The viewer identity is intentionally read-only.

```text
Viewer token compromise
  |
  v
headlamp/headlamp-viewer
  |
  +-- get/list/watch selected resources
  +-- metrics
  +-- no Secrets
  +-- no workload creation
  +-- no RBAC modification
```

This follows Kubernetes least-privilege guidance and avoids turning an externally reachable dashboard into a cluster-admin credential holder.

---

## 23. Future production hardening

Recommended future improvements:

1. Replace ServiceAccount token login with OIDC for individual user identities.
2. Split the shared `platform` AppProject into smaller platform-domain projects.
3. Add NetworkPolicies for Headlamp where your CNI policy model permits.
4. Evaluate `readOnlyRootFilesystem: true` after validating Headlamp runtime requirements.
5. Consider `hostUsers: false` only if user namespaces are supported and tested in the cluster.
6. Add PodDisruptionBudget only if disruption requirements justify it.
7. Add alerting for Certificate readiness and Headlamp availability.
8. Protect `main` with code review / branch protection because Git write access can affect production.

---

## 24. Official resources

### Headlamp

- Installation and authentication  
  https://headlamp.dev/docs/latest/installation/

- In-cluster installation  
  https://headlamp.dev/docs/latest/installation/in-cluster/

- Helm chart documentation  
  https://github.com/kubernetes-sigs/headlamp/blob/main/charts/headlamp/README.md

### Argo CD

- Helm integration  
  https://argo-cd.readthedocs.io/en/latest/user-guide/helm/

- Multiple sources  
  https://argo-cd.readthedocs.io/en/stable/user-guide/multiple_sources/

- Automated sync  
  https://argo-cd.readthedocs.io/en/stable/user-guide/auto_sync/

- Sync options  
  https://argo-cd.readthedocs.io/en/latest/user-guide/sync-options/

- Projects  
  https://argo-cd.readthedocs.io/en/latest/user-guide/projects/

- AppProject specification  
  https://argo-cd.readthedocs.io/en/stable/operator-manual/project-specification/

### Kubernetes

- RBAC good practices  
  https://kubernetes.io/docs/concepts/security/rbac-good-practices/

- RBAC authorization  
  https://kubernetes.io/docs/reference/access-authn-authz/rbac/

- ServiceAccounts  
  https://kubernetes.io/docs/concepts/security/service-accounts/

- `kubectl create token`  
  https://kubernetes.io/docs/reference/generated/kubectl/kubectl-commands#token

### cert-manager

- Certificate resource  
  https://cert-manager.io/docs/usage/certificate/

- Issuer configuration  
  https://cert-manager.io/docs/configuration/

### Traefik

- Kubernetes Ingress provider  
  https://doc.traefik.io/traefik/providers/kubernetes-ingress/

- Kubernetes Ingress routing and TLS  
  https://doc.traefik.io/traefik/master/reference/routing-configuration/kubernetes/ingress/

---

## 25. Final conclusion

The production goal is not simply "deploy Headlamp with Argo CD."

The production goal is:

```text
Git-controlled desired state
        +
Argo CD lifecycle ownership
        +
Pinned upstream Helm chart
        +
Dedicated runtime identity
        +
Dedicated read-only user identity
        +
Least-privilege RBAC
        +
cert-manager certificate lifecycle
        +
Traefik TLS termination
        +
No cluster-admin
        +
Auditable rollback through Git
```

That design keeps Headlamp useful as a platform dashboard without making the dashboard itself a privileged administrative security boundary.

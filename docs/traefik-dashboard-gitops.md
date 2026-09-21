# Traefik dashboard GitOps operations

The `traefik` Argo CD Application owns the upstream Helm release and the
first-party resources in `clusters/production/argocd/resources/traefik`. Its
Git source also supplies the Helm values, keeping this a focused two-source
Application. Argo CD supports a source with both `ref` and `path`: `$values`
still resolves from the repository root while Argo CD also renders the path.

## Ownership and secret flow

| Resource | Owner |
| --- | --- |
| Controller, Service, RBAC, and CRDs | Traefik Helm chart through Argo CD |
| Dashboard route, middleware, Vault mapping, and Certificate | This repository through Argo CD |
| Dashboard htpasswd value | Vault at `kv/traefik/dashboard-basic-auth` |
| Kubernetes authentication Secret | Vault Secrets Operator |
| Dashboard TLS Secret | cert-manager |

The dashboard API is enabled explicitly, while insecure exposure is disabled.
Only the authenticated HTTPS `IngressRoute` exposes `api@internal`.

The Vault KV object must contain a `users` field with an htpasswd-formatted
value such as `admin:<bcrypt-hash>`. Traefik requires at least one valid user;
never commit that value or the generated Kubernetes Secret.

## One-time Vault bootstrap

Run the following from the management host. First authenticate the Vault CLI
inside `vault-0`; the token helper remains inside that pod:

```bash
kubectl exec -n vault -it vault-0 -- sh
export VAULT_ADDR=https://vault-active.vault.svc.cluster.local:8200
export VAULT_CACERT=/vault/userconfig/vault-server-tls/ca.crt
vault login
vault token lookup
exit
```

Create a policy that can read only the dashboard credential:

```bash
printf '%s\n' \
  'path "kv/data/traefik/dashboard-basic-auth" {' \
  '  capabilities = ["read"]' \
  '}' \
  | kubectl exec -n vault -i vault-0 -- sh -lc '
      export VAULT_ADDR=https://vault-active.vault.svc.cluster.local:8200
      export VAULT_CACERT=/vault/userconfig/vault-server-tls/ca.crt
      vault policy write traefik-dashboard -'
```

Bind that policy to the dedicated ServiceAccount and namespace:

```bash
kubectl exec -n vault vault-0 -- sh -lc '
  export VAULT_ADDR=https://vault-active.vault.svc.cluster.local:8200
  export VAULT_CACERT=/vault/userconfig/vault-server-tls/ca.crt
  vault write auth/kubernetes/role/traefik-dashboard \
    bound_service_account_names=traefik-vault-auth \
    bound_service_account_namespaces=traefik \
    audience=vault \
    policies=traefik-dashboard \
    ttl=1h'
```

Preserve the existing login by transferring its htpasswd value directly to
Vault without printing it:

```bash
kubectl get secret dashboard-basic-auth-secret -n traefik \
  -o jsonpath='{.data.users}' \
  | base64 --decode \
  | kubectl exec -n vault -i vault-0 -- sh -lc '
      export VAULT_ADDR=https://vault-active.vault.svc.cluster.local:8200
      export VAULT_CACERT=/vault/userconfig/vault-server-tls/ca.crt
      vault kv put -mount=kv traefik/dashboard-basic-auth users=-'
```

Alternatively, generate a new bcrypt credential and send it directly to Vault:

```bash
read -rsp 'Dashboard password: ' DASHBOARD_PASSWORD
printf '\n'
printf '%s\n' "$DASHBOARD_PASSWORD" \
  | htpasswd -niBC 12 admin \
  | kubectl exec -n vault -i vault-0 -- sh -lc '
      export VAULT_ADDR=https://vault-active.vault.svc.cluster.local:8200
      export VAULT_CACERT=/vault/userconfig/vault-server-tls/ca.crt
      vault kv put -mount=kv traefik/dashboard-basic-auth users=-'
unset DASHBOARD_PASSWORD
```

## Migration order

1. Create the Vault policy, Kubernetes auth role, and KV value.
2. Push the GitOps commit and require the validation workflow to pass.
3. Let the automated `traefik` Application reconcile.
4. Confirm VSO adopted the existing Secret and all resources are healthy.
5. Archive the superseded `/opt/k8s-platform` manifests; do not apply them.

The `VaultStaticSecret` sets `destination.overwrite: true`, the VSO option for
adopting an existing Secret. Argo CD owns the mapping resource, while VSO owns
and continuously reconciles the generated Secret from Vault.

Sync waves order the ServiceAccount, `VaultAuth`, `VaultStaticSecret`, and route.
A wave orders application, but it does not replace resource health checks.

## Verification

```bash
kubectl get application traefik -n argocd
kubectl get vaultauth,vaultstaticsecret -n traefik
kubectl get middleware,ingressroute -n traefik
kubectl get certificate traefik-dashboard-tls -n traefik
kubectl get secret dashboard-basic-auth-secret -n traefik

curl --cacert "$HOME/k8s-certificates/k8s-internal-root-ca.crt" \
  --resolve traefik.k8s.tss.local:443:172.16.6.200 \
  -I https://traefik.k8s.tss.local/dashboard/
```

The trailing slash in `/dashboard/` is required by Traefik. An unauthenticated
request should return `401`; an authenticated request should succeed.

The Certificate requests a 90-day lifetime and renews 15 days before expiry.
The explicit `rotationPolicy: Always` is intentional for the installed
cert-manager v1.15.3, whose default was `Never` before cert-manager v1.18.

## Rotation and rollback

Rotate access by writing a new `users` value to the same Vault path. VSO checks
for changes every five minutes; rotation requires no Git commit. Use the same
stdin-based command from the bootstrap section so the hash is not recorded in
shell history.

For rollback, revert the Git commit before deleting any generated Secret. Keep
the existing Secret until the previous management method is restored and
verified.

## Official references

- [Argo CD multiple sources](https://argo-cd.readthedocs.io/en/latest/user-guide/multiple_sources/)
- [Argo CD sync phases and waves](https://argo-cd.readthedocs.io/en/latest/user-guide/sync-waves/)
- [Traefik v3.7 API and dashboard](https://doc.traefik.io/traefik/v3.7/reference/install-configuration/api-dashboard/)
- [Traefik v3.7 IngressRoute](https://doc.traefik.io/traefik/v3.7/reference/routing-configuration/kubernetes/crd/http/ingressroute/)
- [Traefik BasicAuth](https://doc.traefik.io/traefik/v3.7/reference/routing-configuration/http/middlewares/basicauth/)
- [Vault CLI input from stdin](https://developer.hashicorp.com/vault/docs/commands)
- [VSO authentication](https://developer.hashicorp.com/vault/docs/deploy/kubernetes/vso/sources/vault/auth)
- [VSO API reference](https://developer.hashicorp.com/vault/docs/deploy/kubernetes/vso/api-reference)
- [cert-manager Certificate](https://cert-manager.io/docs/usage/certificate/)

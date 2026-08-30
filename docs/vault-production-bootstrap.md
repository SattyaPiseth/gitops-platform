# Vault production bootstrap and validation

Vault runs as three pods with integrated Raft storage. Argo CD manages the
software, storage claims, TLS certificates, Services, and routing. Vault's
initialization credentials and secret values must never enter Git or Argo CD.

## Bootstrap boundary

The following operations require an authorized operator and secure offline
custody. Perform them only after all three PVCs and pods exist.

```bash
kubectl get pods,pvc,svc -n vault
kubectl wait -n vault --for=condition=Ready certificate/vault-server --timeout=120s

# This prints unseal keys and an initial root token. Capture them directly into
# an approved password manager/HSM workflow; never redirect them into this repo.
kubectl exec -n vault vault-0 -- vault operator init \
  -key-shares=5 -key-threshold=3

# Repeat with three distinct unseal-key shares for vault-0.
kubectl exec -it -n vault vault-0 -- vault operator unseal

# Join followers, then unseal each with three shares.
kubectl exec -n vault vault-1 -- vault operator raft join \
  -leader-ca-cert=@/vault/userconfig/vault-server-tls/ca.crt \
  -leader-client-cert=@/vault/userconfig/vault-server-tls/tls.crt \
  -leader-client-key=@/vault/userconfig/vault-server-tls/tls.key \
  https://vault-0.vault-internal:8200
kubectl exec -it -n vault vault-1 -- vault operator unseal

kubectl exec -n vault vault-2 -- vault operator raft join \
  -leader-ca-cert=@/vault/userconfig/vault-server-tls/ca.crt \
  -leader-client-cert=@/vault/userconfig/vault-server-tls/tls.crt \
  -leader-client-key=@/vault/userconfig/vault-server-tls/tls.key \
  https://vault-0.vault-internal:8200
kubectl exec -it -n vault vault-2 -- vault operator unseal
```

Shamir-sealed pods must be unsealed after restart. Replace this process with a
supported KMS/HSM auto-unseal stanza when an approved key-management service is
available. Back up Raft regularly and test restoration outside production.

## Continuous configuration bootstrap

Authenticate using the initial root token only for bootstrap, then revoke it
once named administrative identities and recovery procedures are established.
Run these commands inside `vault-0` with `VAULT_TOKEN` supplied interactively.

```bash
kubectl exec -it -n vault vault-0 -- sh
export VAULT_ADDR=https://127.0.0.1:8200
export VAULT_CACERT=/vault/userconfig/vault-server-tls/ca.crt
export VAULT_TOKEN='<INITIAL_ROOT_TOKEN>'

vault audit enable file file_path=/vault/audit/audit.log
vault secrets enable -path=kv kv-v2
vault auth enable kubernetes
vault write auth/kubernetes/config \
  kubernetes_host=https://kubernetes.default.svc:443 \
  kubernetes_ca_cert=@/var/run/secrets/kubernetes.io/serviceaccount/ca.crt
```

Create least-privilege policies:

```bash
vault policy write gitlab-platform - <<'HCL'
path "kv/data/gitlab/*" { capabilities = ["read"] }
HCL

vault policy write gitlab-runner - <<'HCL'
path "kv/data/gitlab-runner/auth" { capabilities = ["read"] }
HCL

vault policy write grafana-monitoring - <<'HCL'
path "kv/data/monitoring/grafana" { capabilities = ["read"] }
path "kv/data/monitoring/basic-auth" { capabilities = ["read"] }
HCL

vault write auth/kubernetes/role/gitlab-platform \
  bound_service_account_names=gitlab-vault-auth \
  bound_service_account_namespaces=gitlab \
  policies=gitlab-platform ttl=1h

vault write auth/kubernetes/role/gitlab-runner \
  bound_service_account_names=gitlab-runner-vault-auth \
  bound_service_account_namespaces=gitlab \
  policies=gitlab-runner ttl=1h

vault write auth/kubernetes/role/grafana-monitoring \
  bound_service_account_names=grafana-vault-auth \
  bound_service_account_namespaces=monitoring \
  policies=grafana-monitoring ttl=1h
```

Seed every required KV path with real values through an approved secure
terminal. The key names must match the consuming Helm values:

```text
kv/gitlab/postgresql                 password
kv/gitlab/redis                      password
kv/gitlab/object-storage/rails       connection
kv/gitlab/object-storage/registry    config
kv/gitlab/object-storage/backup      config
kv/gitlab-runner/auth                runner-token
kv/monitoring/grafana                admin-user, admin-password
kv/monitoring/basic-auth             users
```

## Validation

```bash
# Argo CD and Vault workload
kubectl get applications -n argocd
kubectl get pods,pvc,svc,pdb -n vault
kubectl exec -n vault vault-0 -- vault status
kubectl exec -n vault vault-0 -- vault operator raft list-peers

# TLS and external Traefik passthrough
kubectl get certificate,secret -n vault
openssl s_client -connect vault.k8s.tss.local:443 \
  -servername vault.k8s.tss.local -CAfile /secure/path/to/internal-ca.crt </dev/null
curl --cacert /secure/path/to/internal-ca.crt \
  https://vault.k8s.tss.local/v1/sys/health

# VSO reconciliation
kubectl get vaultconnection -A
kubectl get vaultauth -A
kubectl get vaultstaticsecret -A
kubectl describe vaultconnection default -n vault-secrets-operator-system
kubectl get secret gitlab-runner-secret -n gitlab
kubectl get secret grafana-admin-credentials -n monitoring

# GitLab workload and policy behavior
kubectl get pods -n gitlab
kubectl get networkpolicy -n gitlab
kubectl exec -n gitlab deploy/gitlab-runner -- getent hosts postgres.k8s.tss.local
```

Do not declare the rollout complete until `VaultConnection.status.valid=true`,
all VaultAuth/VaultStaticSecret conditions are healthy, at least one test
secret has synchronized, and its consuming workload becomes Ready.

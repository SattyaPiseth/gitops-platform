# Manual Certificate Renewal Guide

This runbook covers manual renewal of cert-manager `Certificate` resources on
the production Kubernetes cluster. It does not cover API server, etcd,
kubelet, or front-proxy certificates. Kubernetes PKI lifecycle belongs to
Kubespray and must not be managed with `cmctl`.

Routine service-certificate renewal is automatic. Use manual renewal only for
a CA replacement, chain mismatch, compromised key, changed certificate
requirements, or a controlled issuance test.

## Trust model

| Issuer | Purpose |
| --- | --- |
| `ClusterIssuer/selfsigned-bootstrap` | Creates the internal root CA Certificate only. |
| `ClusterIssuer/k8s-internal-ca` | Issues service certificates from `cert-manager/k8s-internal-root-ca-secret`. |
| Namespace-scoped issuers | Protect CNPG, Barman, and GitLab PostgreSQL traffic independently. |

The public trust anchor is `ca.crt` in
`cert-manager/k8s-internal-root-ca-secret`. Never distribute `tls.key`.

## Safety rules

1. Renew one Certificate at a time.
2. Verify cluster and issuer health before starting.
3. Never edit `tls.crt` or `tls.key` and never delete a TLS Secret to force
   issuance.
4. Confirm that the Secret serial changes. `Ready=True` may remain visible
   while issuance is in progress.
5. Verify the new chain before reloading a workload.
6. For Vault, reload standbys first and the active member last. Do not restart
   manually unsealed Vault pods merely to load a certificate.
7. Stop if the new chain fails or a workload becomes unhealthy.

## Preflight

```bash
kubectl get --raw='/readyz?verbose'
kubectl get nodes
kubectl get pods -A \
  --field-selector=status.phase!=Running,status.phase!=Succeeded
kubectl get clusterissuers.cert-manager.io
kubectl get certificates.cert-manager.io -A \
  -o custom-columns='NAMESPACE:.metadata.namespace,NAME:.metadata.name,READY:.status.conditions[0].status,NOT-AFTER:.status.notAfter,ISSUER:.spec.issuerRef.name'
```

Proceed only when the API is ready, every node is `Ready`, no unexpected pod
is failed or pending, and the required issuer reports `Ready=True`.

Confirm authorization for the target namespace:

```bash
namespace=monitoring
secret=grafana-tls

kubectl auth can-i update certificates/status.cert-manager.io \
  -n "$namespace"
kubectl auth can-i get secret/"$secret" -n "$namespace"
```

Install `cmctl` using the official cert-manager instructions and verify its
checksum. Do not store downloaded tools in this repository.

### Where and how to run `cmctl`

Run `cmctl` from an authenticated management workstation such as
`ubuntu-24-04-mgmt-01`. It does not need to be installed on every control-plane
or worker node. Avoid installing administrative tools on workers.

Confirm the active Kubernetes context before using it:

```bash
kubectl config current-context
kubectl auth whoami
kubectl get --raw='/readyz'
```

If a checksum-verified temporary binary is available, run it by its absolute
path:

```bash
/tmp/cmctl-v2.5.0 version --client
/tmp/cmctl-v2.5.0 renew grafana-tls -n monitoring
```

Files under `/tmp` are temporary and may disappear after a reboot or system
cleanup. To keep the verified binary on the management workstation, install it
with controlled ownership and permissions:

```bash
sudo install \
  -o root -g root -m 0755 \
  /tmp/cmctl-v2.5.0 \
  /usr/local/bin/cmctl

command -v cmctl
cmctl version --client
```

The expected permanent path is `/usr/local/bin/cmctl`. A permanent installation
does not grant Kubernetes access by itself; `cmctl` uses the current kubeconfig
and the caller's Kubernetes RBAC permissions.

## Renew one service Certificate

Set the target explicitly:

```bash
namespace=monitoring
certificate=grafana-tls
secret=grafana-tls
```

Record the old public serial without displaying the Secret or private key:

```bash
old_serial="$({
  kubectl get secret "$secret" -n "$namespace" \
    -o jsonpath='{.data.tls\.crt}' |
    base64 --decode
} | openssl x509 -noout -serial)"

printf 'Old %s\n' "$old_serial"
```

Trigger supported manual renewal:

```bash
cmctl renew "$certificate" -n "$namespace"
```

Wait for a different serial, then confirm cert-manager readiness:

```bash
for attempt in $(seq 1 24); do
  new_serial="$({
    kubectl get secret "$secret" -n "$namespace" \
      -o jsonpath='{.data.tls\.crt}' |
      base64 --decode
  } | openssl x509 -noout -serial 2>/dev/null || true)"

  if [[ -n "$new_serial" && "$new_serial" != "$old_serial" ]]; then
    break
  fi
  sleep 5
done

test "$new_serial" != "$old_serial"
kubectl wait certificate/"$certificate" -n "$namespace" \
  --for=condition=Ready --timeout=120s
```

## Verify the new chain

Extract public certificates only:

```bash
review_dir="$(mktemp -d)"
chmod 700 "$review_dir"

kubectl get secret k8s-internal-root-ca-secret -n cert-manager \
  -o jsonpath='{.data.ca\.crt}' |
  base64 --decode >"$review_dir/root-ca.crt"
kubectl get secret "$secret" -n "$namespace" \
  -o jsonpath='{.data.tls\.crt}' |
  base64 --decode >"$review_dir/service.crt"

openssl verify -CAfile "$review_dir/root-ca.crt" \
  "$review_dir/service.crt"
openssl x509 -in "$review_dir/service.crt" \
  -noout -subject -issuer -serial -dates -fingerprint -sha256
rm -rf "$review_dir"
```

Expected result: `service.crt: OK`.

Verify a resolvable HTTPS endpoint presents a hostname-valid chain:

```bash
hostname=grafana.k8s.tss.local
ca_file="$(mktemp)"
kubectl get secret k8s-internal-root-ca-secret -n cert-manager \
  -o jsonpath='{.data.ca\.crt}' | base64 --decode >"$ca_file"

openssl s_client \
  -connect "$hostname:443" \
  -servername "$hostname" \
  -verify_hostname "$hostname" \
  -CAfile "$ca_file" \
  -verify_return_error </dev/null
rm -f "$ca_file"
```

## Workload reload behavior

Traefik watches referenced TLS Secrets, so certificates for the current Argo
CD, GitLab, Headlamp, Longhorn, MinIO, Alertmanager, Grafana, Prometheus, and
Traefik dashboard routes normally become active without restarting the
application. Verify the endpoint before considering a restart.

Vault terminates TLS itself and retains the loaded certificate in memory.
Kubernetes may project the renewed Secret into the pod while Vault continues
serving the old certificate.

### Vault reload procedure

Confirm all members are unsealed and identify the active member:

```bash
for pod in vault-0 vault-1 vault-2; do
  echo "$pod"
  kubectl exec -n vault "$pod" -- sh -c \
    'VAULT_ADDR=https://127.0.0.1:8200 vault status -tls-skip-verify -format=json' |
    jq '{sealed,is_self,leader_address}'
done
```

Confirm every pod has received the new public certificate:

```bash
for pod in vault-0 vault-1 vault-2; do
  printf '%s: ' "$pod"
  kubectl exec -n vault "$pod" -- \
    cat /vault/userconfig/vault-server-tls/tls.crt |
    openssl x509 -noout -serial
done
```

Find the Vault process; do not assume that its PID is permanent:

```bash
kubectl exec -n vault vault-1 -- ps -eo pid,ppid,comm,args
```

Send `SIGHUP` to the actual `vault server` process, standbys first and the
active member last:

```bash
reload_vault_tls() {
  local pod="$1"
  local vault_pid

  vault_pid="$(kubectl exec -n vault "$pod" -- sh -c \
    "ps -eo pid,comm | awk '\$2 == \"vault\" { print \$1; exit }'")"
  test -n "$vault_pid"
  kubectl exec -n vault "$pod" -- kill -HUP "$vault_pid"
}

reload_vault_tls vault-1
reload_vault_tls vault-2
reload_vault_tls vault-0
```

After each signal, verify that the pod did not restart, remains unsealed, and
serves the new serial. Stop before signaling the next member if a check fails.

```bash
kubectl get pods -n vault
kubectl get vaultconnection default \
  -n vault-secrets-operator-system \
  -o jsonpath='{.status.valid}{"\n"}'
```

## Separate application trust domains

Do not renew these Certificates using `k8s-internal-ca`:

- CNPG Barman client and server certificates use
  `Issuer/plugin-barman-cloud-selfsigned-issuer`.
- GitLab PostgreSQL server and replication certificates use
  `Issuer/gitlab-postgresql-tls-ca`.
- The GitLab PostgreSQL CA uses
  `Issuer/gitlab-postgresql-selfsigned`.

They are not expected to verify against `k8s-internal-root-ca-secret`.

## Root CA rotation warning

Leaf renewal is different from root CA rotation. Replacing the key or
certificate in `k8s-internal-root-ca-secret` does not guarantee immediate
renewal of existing leaves. Root rotation requires a planned trust-overlap
period, renewal and verification of every dependent Certificate, and removal
of the old trust anchor only after every consumer has migrated.

Do not renew or replace `Certificate/k8s-internal-root-ca` as part of ordinary
service-certificate maintenance.

## Final validation

```bash
kubectl get certificates.cert-manager.io -A
kubectl get applications.argoproj.io -n argocd
kubectl get nodes
kubectl get pods -A \
  --field-selector=status.phase!=Running,status.phase!=Succeeded
kubectl get volumes.longhorn.io -n longhorn-system
kubectl get pods -n vault
kubectl get vaultconnection default -n vault-secrets-operator-system
kubectl get --raw='/readyz'
```

## Official references

- [cert-manager `cmctl` reference](https://cert-manager.io/docs/reference/cmctl/)
- [cert-manager Certificate renewal](https://cert-manager.io/docs/usage/certificate/)
- [cert-manager CA issuer](https://cert-manager.io/docs/configuration/ca/)
- [Vault TCP listener configuration](https://developer.hashicorp.com/vault/docs/configuration/listener/tcp)

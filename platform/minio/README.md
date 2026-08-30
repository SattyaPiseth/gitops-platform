# MinIO pre-production object storage

This directory defines the initial in-cluster S3-compatible endpoint for
`s3.k8s.tss.local`. It is intentionally classified as **pre-production**.
The Tenant shares the Kubernetes and Longhorn failure domain with its clients
and is not an independent disaster-recovery copy.

## Architecture and capacity

- Argo CD installs the pinned MinIO Operator and then the Tenant chart at
  version `7.1.1`.
- cert-manager issues one internal-CA certificate for both the public S3 name
  and the Tenant's internal service names. Traefik validates that certificate
  on the backend connection; TLS is not terminated and then downgraded.
- Traefik exposes only the S3 API at `https://s3.k8s.tss.local`. The MinIO
  Console and direct LoadBalancer services remain disabled.
- The initial distributed pool has four servers, one 25 GiB PVC per server,
  and approximately 100 GiB raw capacity. Erasure-code parity means usable
  capacity is materially lower (normally about 50 GiB for this four-drive
  layout); measure the actual result after deployment.
- `longhorn-minio` uses one strict-local Longhorn replica. This avoids storing
  multiple Longhorn replicas beneath MinIO erasure coding, but a node or disk
  loss can leave its shard unavailable until that storage is recovered.
- Four MinIO pods share three storage workers, so one worker must host two
  pods. This cannot meet a strict one-server-per-failure-domain design.

The DNS record already points at the Traefik VIP `172.16.6.200`. Until the
Tenant and IngressRoute are synced, clients may receive Traefik's default
certificate or a routing error; that is expected and does not indicate that
MinIO is installed.

## Deployment order

1. Push the GitOps commit. Argo CD may automatically sync `minio-operator` and
   `minio-prerequisites`; the `minio` Tenant Application remains manual.
2. Configure the Vault policy and Kubernetes auth role shown below.
3. Seed `kv/minio/root` with a URL-safe root password that does not contain a
   single quote. Never commit or print the value.
4. Verify `Secret/minio-root-credentials` contains only `config.env` and that
   `Certificate/minio-server-tls` is Ready.
5. Review Longhorn scheduled capacity, then manually sync `Application/minio`.
6. Validate Tenant health, TLS, metrics, buckets, and node-loss behavior.
7. Create separate least-privilege users for GitLab Rails, Registry, backups,
   and CNPG backups. Store those credentials in Vault, not Git.

Do not point GitLab or CNPG at the Tenant using the root credential. The three
GitLab Vault entries already define separate client credential sets, but the
matching MinIO identities and bucket policies still have to be provisioned and
tested before those clients are enabled.

## Vault policy and role

Run these commands from an authenticated Vault shell:

```bash
vault policy write minio-platform - <<'EOF'
path "kv/data/minio/root" {
  capabilities = ["read"]
}
EOF

vault write auth/kubernetes/role/minio-platform \
  bound_service_account_names=minio-vault-auth \
  bound_service_account_namespaces=minio-system \
  audience=vault \
  token_policies=minio-platform \
  token_ttl=1h

read -rsp 'Enter generated URL-safe MinIO root password: ' MINIO_ROOT_PASSWORD
echo
vault kv put kv/minio/root \
  root-user=minio-root \
  root-password="${MINIO_ROOT_PASSWORD}"
unset MINIO_ROOT_PASSWORD
```

Use a generated password containing only URL-safe characters and no single
quote. The VSO template deliberately single-quotes the value in `config.env`
so shell metacharacters are not expanded by MinIO's environment-file parser.

## Pre-sync checks

```bash
kubectl get application -n argocd minio-operator minio-prerequisites minio
kubectl get vaultauth,vaultstaticsecret -n minio-system
kubectl get secret -n minio-system minio-root-credentials \
  -o go-template='{{range $key, $value := .data}}{{printf "%s\n" $key}}{{end}}'
kubectl get certificate -n minio-system minio-server-tls
kubectl get storageclass longhorn-minio
```

Expected Secret key: `config.env`. Do not decode or print it.

After those checks pass, explicitly sync the gated Tenant application:

```bash
argocd app sync minio
kubectl wait --for=condition=Ready pod \
  -l v1.min.io/tenant=minio -n minio-system --timeout=15m
kubectl get tenant minio -n minio-system \
  -o custom-columns=STATE:.status.currentState,HEALTH:.status.healthStatus,ONLINE:.status.drivesOnline,OFFLINE:.status.drivesOffline
kubectl get pods,pvc,svc -n minio-system -o wide
```

Verify that all four pods and PVCs are healthy before testing through Traefik:

```bash
kubectl get secret minio-server-tls -n minio-system \
  -o jsonpath='{.data.ca\.crt}' | base64 -d > /tmp/minio-ca.crt
curl --fail --show-error --cacert /tmp/minio-ca.crt \
  https://s3.k8s.tss.local/minio/health/cluster
kubectl get servicemonitor,prometheusrule -n minio-system
```

Remove `/tmp/minio-ca.crt` after testing. It contains only the public CA
certificate, not a private key.

## Backup, replication, and restore gate

Longhorn volumes, replicas, and snapshots in this cluster are availability
mechanisms, not off-cluster backups. GitLab archives or CNPG backups stored in
this Tenant are also lost if the Kubernetes/Longhorn failure domain is lost.

Before production approval:

1. Provide a second, independently administered object-storage target outside
   this cluster and failure domain.
2. Enable bucket versioning where recovery from overwrite or deletion is
   required, especially Terraform state and backup buckets.
3. Configure authenticated MinIO bucket/site replication or a scheduled,
   monitored mirror to that target. Replication credentials must be scoped and
   stored in Vault.
4. Define measurable RPO/RTO targets, retention, immutability requirements,
   capacity alerts, and ownership for failed replication.
5. Run a restore drill into isolated test namespaces: restore a versioned test
   object, a GitLab backup, and a CNPG backup; verify application integrity and
   record timings and checksums.
6. Repeat the restore drill after credential rotation and on a regular
   schedule. A successful upload is not proof that a backup is restorable.

Do not mark the service production-ready until an off-cluster copy and the
restore drill both succeed.

## Production blockers

- Four MinIO servers are distributed over only three storage workers.
- The initial pool is only four 25 GiB drives and is intended for validation.
- Longhorn stores one strict-local replica per MinIO PVC.
- No independently administered off-cluster replica currently exists.
- The MinIO community Operator/server lifecycle is an accepted temporary risk.
- Workload identities and bucket-scoped policies are not provisioned by this
  initial infrastructure stage.
- Restore, node-loss, credential-rotation, capacity, and performance tests are
  required before production approval.

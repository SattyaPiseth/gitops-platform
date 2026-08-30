# GitLab Redis / Sentinel

GitLab discovers the writable Redis primary through Sentinel. This is a private, in-cluster service; no Traefik TCP router or external DNS record is required.

- Sentinel master group: `mymaster`
- Sentinel discovery: `gitlab-redis-s-hl.gitlab.svc.cluster.local:26379`
- Redis port: `6379`
- Kubernetes Secret: `gitlab-redis`
- Secret key: `password`
- Vault source: `kv/data/gitlab/redis`
- Topology: three Redis replication pods and three Sentinel pods, spread across storage workers
- Persistence: 10 Gi Longhorn PVC per Redis pod, AOF enabled

The Redis Operator and workload charts are pinned in the Argo CD applications. GitLab itself remains manually synced so Redis health can be confirmed before switching application workloads.

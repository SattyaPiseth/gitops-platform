# GitLab PostgreSQL

PostgreSQL is managed by CloudNativePG in the gitlab namespace as a
three-instance cluster with Longhorn-backed data and WAL volumes.

## Application connection

Host: gitlab-postgresql-rw.gitlab.svc.cluster.local
Port: 5432
Database: gitlabhq_production
Role: gitlab
Secret: gitlab-postgresql
Password key: password

The gitlab-postgresql Secret is synchronized from kv/gitlab/postgresql by
Vault Secrets Operator. VSO transforms it to a kubernetes.io/basic-auth Secret
containing username and password for both CNPG bootstrap and the GitLab chart.

The required amcheck, btree_gist, and pg_trgm extensions are installed during
initial database bootstrap.

## Operations

The Cluster resource is protected from automatic Argo CD pruning. Removing it
from Git does not authorize database deletion. Verify tested backups before any
destructive database operation.

Longhorn replication provides storage availability, not a database backup.
Configure an approved object-store backup target and test restoration before
declaring the database production-ready.

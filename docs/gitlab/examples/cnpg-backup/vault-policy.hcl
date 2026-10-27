# Merge into the policy assigned to the existing gitlab-platform Vault role.
# Do not overwrite its other required grants.
path "kv/data/gitlab/postgresql-backup" {
  capabilities = ["read"]
}

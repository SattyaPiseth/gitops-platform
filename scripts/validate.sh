#!/usr/bin/env bash

set -euo pipefail

REPOSITORY_ROOT="$(git rev-parse --show-toplevel)"
readonly REPOSITORY_ROOT
readonly APPLICATION_DIRECTORY="clusters/production/argocd/applications"
readonly KUBECONFORM_IMAGE="ghcr.io/yannh/kubeconform:v0.8.0"
readonly GITLEAKS_IMAGE="ghcr.io/gitleaks/gitleaks:v8.30.0"

cd "$REPOSITORY_ROOT"

for command_name in git helm docker python3 yamllint shellcheck; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    printf 'Required command is unavailable: %s\n' "$command_name" >&2
    exit 1
  fi
done

echo 'Checking Git patches...'
git diff --check
git diff --cached --check

echo 'Linting tracked YAML...'
git ls-files -z '*.yaml' '*.yml' | xargs -0 --no-run-if-empty yamllint

echo 'Checking Argo CD discovery directories...'
invalid_files="$(find "$APPLICATION_DIRECTORY" \
  -maxdepth 1 -type f ! -name '*.yaml' ! -name '*.yml' -print)"
if [[ -n "$invalid_files" ]]; then
  printf 'Unsupported files in the Argo application directory:\n%s\n' \
    "$invalid_files" >&2
  exit 1
fi

echo 'Checking Markdown links...'
python3 scripts/check_markdown_links.py

echo 'Linting shell scripts...'
mapfile -d '' shell_scripts < <(git ls-files -z '*.sh')
if ((${#shell_scripts[@]} > 0)); then
  shellcheck "${shell_scripts[@]}"
fi

render_directory="$(mktemp -d)"
trap 'rm -rf "$render_directory"' EXIT

echo 'Updating pinned Helm repositories...'
helm repo add --force-update cnpg https://cloudnative-pg.github.io/charts
helm repo add --force-update gitlab https://charts.gitlab.io/
helm repo add --force-update headlamp https://kubernetes-sigs.github.io/headlamp/
helm repo add --force-update longhorn https://charts.longhorn.io
helm repo add --force-update minio https://operator.min.io
helm repo add --force-update opstree https://ot-container-kit.github.io/helm-charts
helm repo add --force-update prometheus-community https://prometheus-community.github.io/helm-charts
helm repo add --force-update csr-approver https://postfinance.github.io/kubelet-csr-approver
helm repo add --force-update traefik https://traefik.github.io/charts
helm repo add --force-update hashicorp https://helm.releases.hashicorp.com
helm repo update

render_chart() {
  local release_name="$1"
  local chart_name="$2"
  local chart_version="$3"
  local namespace="$4"
  shift 4

  echo "Rendering ${release_name} (${chart_name} ${chart_version})..."
  helm template "$release_name" "$chart_name" \
    --version "$chart_version" \
    --namespace "$namespace" \
    --include-crds \
    "$@" >"${render_directory}/${release_name}.yaml"
}

render_chart cnpg cnpg/cloudnative-pg 0.29.0 cnpg-system --values helm-values/cnpg/values.yaml
render_chart gitlab-redis opstree/redis-replication 0.17.1 gitlab --values helm-values/gitlab/redis-values.yaml
render_chart gitlab-runner gitlab/gitlab-runner 0.91.3 gitlab --values helm-values/gitlab-runner/values.yaml
render_chart gitlab gitlab/gitlab 10.2.4 gitlab --values helm-values/gitlab/values.yaml --values helm-values/gitlab/values-production.yaml
render_chart headlamp headlamp/headlamp 0.43.0 headlamp --values helm-values/headlamp/values.yaml
render_chart kube-prometheus-stack prometheus-community/kube-prometheus-stack 87.21.0 monitoring --values helm-values/kube-prometheus-stack/values.yaml
render_chart kubelet-csr-approver csr-approver/kubelet-csr-approver 1.1.0 kube-system --values helm-values/kubelet-csr-approver/values.yaml
render_chart longhorn longhorn/longhorn 1.12.0 longhorn-system --values helm-values/longhorn/values.yaml
render_chart minio-operator minio/operator 7.1.1 minio-operator --values helm-values/minio-operator/values.yaml
render_chart minio minio/tenant 7.1.1 minio-system --values helm-values/minio/values.yaml
render_chart plugin-barman-cloud cnpg/plugin-barman-cloud 0.7.1 cnpg-system
render_chart redis-operator opstree/redis-operator 0.26.1 redis-operator --values helm-values/redis-operator/values.yaml
render_chart traefik traefik/traefik 41.3.0 traefik --values helm-values/traefik/values.yaml
render_chart vault-secrets-operator hashicorp/vault-secrets-operator 0.9.1 vault-secrets-operator-system --values helm-values/vault-secrets-operator/values.yaml
render_chart vault hashicorp/vault 0.32.0 vault --values helm-values/vault/values.yaml

echo 'Validating first-party Kubernetes resources...'
docker run --rm --volume "$REPOSITORY_ROOT:/work:ro" "$KUBECONFORM_IMAGE" \
  -strict -summary -ignore-missing-schemas /work/clusters /work/platform

echo 'Validating rendered Helm resources...'
docker run --rm --volume "$render_directory:/rendered:ro" "$KUBECONFORM_IMAGE" \
  -strict -summary -ignore-missing-schemas /rendered

echo 'Validating Traefik GitLab Shell entrypoint...'
grep --fixed-strings --quiet -- '--entryPoints.gitlab-shell.address=:2222/tcp' \
  "$render_directory/traefik.yaml"
grep --fixed-strings --quiet 'name: gitlab-shell' "$render_directory/traefik.yaml"

echo 'Scanning Git history for secrets...'
docker run --rm --volume "$REPOSITORY_ROOT:/repo:ro" "$GITLEAKS_IMAGE" \
  detect --source=/repo --no-banner --redact

echo 'Validation completed successfully.'

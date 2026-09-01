#!/bin/bash

set -euo pipefail



# Default values
REMOTE="origin"
BRANCH=$(git rev-parse --abbrev-ref HEAD)
COMMIT_MSG=""
AUTO_PULL=false

usage() {
  echo "Usage: $0 [options] [commit-message]"
  echo
  echo "Options:"
  echo "  -r, --remote <remote>       Specify remote to push (default: origin)"
  echo "  -b, --branch <branch>       Specify branch to push (default: current branch)"
  echo "  -p, --pull                  Auto git pull before push"
  echo "  -h, --help                  Show this help message"
  echo
  echo "Examples:"
  echo "  $0 \"Update docs\""
  echo "  $0 -r origin -b develop \"Fix bug\""
  echo "  $0 --pull"
  echo
  exit 0
}

# Parse args
while [[ $# -gt 0 ]]; do
  case $1 in
    -r|--remote)
      if [[ $# -lt 2 ]]; then
        echo "Missing value for $1." >&2
        exit 2
      fi
      REMOTE="$2"
      shift 2
      ;;
    -b|--branch)
      if [[ $# -lt 2 ]]; then
        echo "Missing value for $1." >&2
        exit 2
      fi
      BRANCH="$2"
      shift 2
      ;;
    -p|--pull)
      AUTO_PULL=true
      shift
      ;;
    -h|--help)
      usage
      ;;
    *)
      if [[ -z "$COMMIT_MSG" ]]; then
        COMMIT_MSG="$1"
      fi
      shift
      ;;
  esac
done

# Commit message logic
if [[ -z "$COMMIT_MSG" ]]; then
  COMMIT_MSG="Auto update: $(date '+%Y-%m-%d %H:%M:%S')"
fi

# Auto pull if requested
if [[ "$REMOTE" == -* || "$BRANCH" == -* ]]; then
  echo "Remote and branch names must not begin with '-'." >&2
  exit 2
fi

if ! git remote get-url "$REMOTE" >/dev/null 2>&1; then
  echo "Git remote '$REMOTE' does not exist." >&2
  exit 2
fi

if $AUTO_PULL; then
  echo "Pulling latest changes from $REMOTE/$BRANCH..."
  git pull --rebase "$REMOTE" "$BRANCH"
fi

echo "Adding all changes..."
echo "Checking worktree patches..."
git diff --check

if command -v gitleaks >/dev/null 2>&1; then
  echo "Scanning worktree for secrets..."
  gitleaks dir . --no-banner --redact
fi

git add --all

echo "Checking staged patches..."
git diff --cached --check

if git diff --cached --quiet; then
  echo "Nothing to commit."
  exit 0
fi

echo "Committing with message: $COMMIT_MSG"
git commit -m "$COMMIT_MSG"

echo "Pushing to $REMOTE $BRANCH..."
git push -- "$REMOTE" "$BRANCH"

echo "Push complete."
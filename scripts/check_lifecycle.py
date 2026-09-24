#!/usr/bin/env python3
"""Check Argo CD deletion boundaries; this does not validate live protection."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

SYNC_OPTIONS = 'argocd.argoproj.io/sync-options'
APPROVAL = 'argocd.argoproj.io/deletion-approved'


def resource_errors(resource: dict) -> list[str]:
    """Enforce protections at the resource's owning Application boundary."""
    metadata = resource.get('metadata') or {}
    annotations = metadata.get('annotations') or {}
    kind = resource.get('kind')
    api_group = str(resource.get('apiVersion', '')).split('/')[0]
    errors = []
    if APPROVAL in annotations:
        errors.append('deletion approval must be an operational action, never committed')

    protected = (
        (api_group == 'argoproj.io' and kind in ('Application', 'AppProject')
         and not (kind == 'Application' and metadata.get('name') == 'root-applications'))
        or (resource.get('apiVersion') == 'v1' and kind == 'Namespace')
        or (api_group == 'postgresql.cnpg.io' and kind == 'Cluster')
    )
    if not protected:
        return errors

    options = {}
    for item in str(annotations.get(SYNC_OPTIONS, '')).split(','):
        if '=' not in item:
            continue
        key, value = (part.strip() for part in item.split('=', 1))
        if key in options:
            errors.append(f'duplicate sync option: {key}')
        options[key] = value

    for key in ('Prune', 'Delete'):
        allowed = {'false'} if api_group == 'postgresql.cnpg.io' else {'confirm', 'false'}
        if options.get(key) not in allowed:
            errors.append(f'{key} must be one of {sorted(allowed)} in metadata annotations')
    return errors


def check_repository(root: Path) -> list[str]:
    errors = []
    for directory in ('clusters', 'platform'):
        for path in sorted((root / directory).rglob('*')):
            if path.suffix not in ('.yaml', '.yml'):
                continue
            try:
                for resource in yaml.safe_load_all(path.read_text()):
                    if not isinstance(resource, dict):
                        continue
                    metadata = resource.get('metadata') or {}
                    name = metadata.get('name', '<unnamed>')
                    for message in resource_errors(resource):
                        errors.append(f'{path.relative_to(root)}: {name}: {message}')
            except yaml.YAMLError as error:
                errors.append(f'{path.relative_to(root)}: invalid YAML: {error}')
    return errors


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    errors = check_repository(root)
    if errors:
        print('Lifecycle validation failed:', file=sys.stderr)
        print('\n'.join(errors), file=sys.stderr)
        return 1
    print('Lifecycle deletion boundaries validated (repository configuration only).')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

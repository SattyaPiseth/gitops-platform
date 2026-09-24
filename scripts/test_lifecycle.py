"""Regression checks for deletion paths that manual synchronization cannot guard."""

import tempfile
import unittest
from pathlib import Path

from check_lifecycle import APPROVAL, SYNC_OPTIONS, check_repository, resource_errors


def resource(kind='Application', options='Prune=confirm,Delete=confirm'):
    group = {'Namespace': 'v1', 'Cluster': 'postgresql.cnpg.io/v1'}.get(
        kind, 'argoproj.io/v1alpha1'
    )
    return {
        'apiVersion': group,
        'kind': kind,
        'metadata': {'name': 'example', 'annotations': {SYNC_OPTIONS: options}},
    }


class LifecycleTests(unittest.TestCase):
    def test_both_parent_deletion_paths_are_guarded(self):
        for kind in ('Application', 'AppProject', 'Namespace'):
            with self.subTest(kind=kind):
                self.assertEqual(resource_errors(resource(kind)), [])
                self.assertTrue(resource_errors(resource(kind, 'Prune=confirm')))
                self.assertTrue(resource_errors(resource(kind, 'Delete=confirm')))

    def test_manual_sync_is_not_deletion_protection(self):
        app = resource(options='')
        app['spec'] = {'syncPolicy': {'syncOptions': ['CreateNamespace=true']}}
        self.assertEqual(len(resource_errors(app)), 2)

    def test_application_level_options_do_not_protect_the_application(self):
        app = resource(options='')
        app['spec'] = {'syncPolicy': {'syncOptions': ['Prune=confirm', 'Delete=confirm']}}
        self.assertEqual(len(resource_errors(app)), 2)

    def test_database_must_be_retained_on_both_paths(self):
        self.assertEqual(resource_errors(resource('Cluster', 'Prune=false,Delete=false')), [])
        self.assertTrue(resource_errors(resource('Cluster')))
        self.assertTrue(resource_errors(resource('Cluster', 'Prune=false')))

    def test_operational_approval_cannot_be_committed(self):
        app = resource()
        app['metadata']['annotations'][APPROVAL] = '2026-09-24T00:00:00Z'
        self.assertTrue(resource_errors(app))

    def test_duplicate_options_are_rejected(self):
        self.assertTrue(resource_errors(resource(options='Prune=true,Prune=confirm,Delete=confirm')))

    def test_whitespace_and_stronger_retention_are_supported(self):
        self.assertEqual(resource_errors(resource(options=' Prune=false, Delete=false ')), [])

    def test_unmanaged_root_is_exempt_but_cannot_store_approval(self):
        app = resource(options='')
        app['metadata']['name'] = 'root-applications'
        self.assertEqual(resource_errors(app), [])
        app['metadata']['annotations'][APPROVAL] = '2026-09-24T00:00:00Z'
        self.assertTrue(resource_errors(app))

    def test_nested_multidocument_manifests_are_checked(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / 'platform' / 'example'
            target.mkdir(parents=True)
            (target / 'objects.yml').write_text(
                'apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: config\n'
                '---\napiVersion: v1\nkind: Namespace\nmetadata:\n  name: data\n'
            )
            self.assertEqual(len(check_repository(root)), 2)


if __name__ == '__main__':
    unittest.main()

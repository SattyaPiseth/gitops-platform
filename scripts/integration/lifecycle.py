#!/usr/bin/env python3
"""Exercise real Argo CD deletion paths only in a newly created Kind cluster."""

import argparse
import datetime
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
import uuid

import yaml

ROOT = Path(__file__).resolve().parents[2]
GUARD = 'argocd.argoproj.io/sync-options'
FINALIZER = 'resources-finalizer.argocd.argoproj.io'
NODE = 'kindest/node:v1.35.0@sha256:452d707d4862f52530247495d180205e029056831160e22870e37e3f6c1ac31f'


def run(*args, stdin=None, cwd=None, check=True):
    result = subprocess.run(args, input=stdin, cwd=cwd, text=True,
                            capture_output=True, timeout=600)
    if check and result.returncode:
        raise RuntimeError(f'{args[:4]} failed: {result.stderr[-4000:]}')
    return result.stdout.strip()


def stamp():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def wait(description, predicate, timeout=240):
    print(f'Waiting: {description}', flush=True)
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        result = predicate()
        if result:
            return result
        time.sleep(3)
    raise TimeoutError(description)


class Suite:
    def __init__(self, directory, evidence):
        self.work = Path(directory)
        self.evidence = evidence
        self.name = 'lifecycle-' + uuid.uuid4().hex[:10]
        self.kubeconfig = self.work / 'kubeconfig'
        self.repo = self.work / 'fixtures.git'
        self.checkout = self.work / 'fixtures'
        self.report = {'started_at': stamp(), 'cluster': self.name,
                       'source_revision': run('git', 'rev-parse', 'HEAD', cwd=ROOT),
                       'scope': 'Disposable single-node Kind; not production or backup/restore proof',
                       'tests': []}
        self.guard = yaml.safe_load((ROOT / 'clusters/production/argocd/applications/gitlab.yaml').read_text())['metadata']['annotations'][GUARD]
        self.ns_guard = yaml.safe_load((ROOT / 'platform/gitlab/namespace.yaml').read_text())['metadata']['annotations'][GUARD]
        self.database = next(yaml.safe_load_all((ROOT / 'platform/gitlab/database/cluster.yaml').read_text()))

    def k(self, *args, stdin=None):
        # Every API operation names the newly created kubeconfig AND context.
        return run('kubectl', '--kubeconfig', str(self.kubeconfig),
                   '--context', 'kind-' + self.name, '--request-timeout=30s',
                   *args, stdin=stdin)

    def get(self, kind, name, namespace=None):
        args = ['get', kind, name, '--ignore-not-found', '-o', 'json']
        if namespace:
            args += ['-n', namespace]
        value = self.k(*args)
        return json.loads(value) if value else None

    def apply(self, obj):
        self.k('apply', '-f', '-', stdin=yaml.safe_dump(obj))

    def app(self, name, path, revision, namespace='lifecycle-tests'):
        return {'apiVersion': 'argoproj.io/v1alpha1', 'kind': 'Application',
                'metadata': {'name': name, 'namespace': 'argocd',
                             'annotations': {GUARD: self.guard}, 'finalizers': [FINALIZER]},
                'spec': {'project': 'default', 'source': {'repoURL': self.url,
                         'targetRevision': revision, 'path': path},
                         'destination': {'server': 'https://kubernetes.default.svc', 'namespace': namespace},
                         'syncPolicy': {'automated': {'prune': True, 'selfHeal': True, 'allowEmpty': True}}}}

    def commit(self, path, objects):
        target = self.checkout / path
        target.mkdir(parents=True, exist_ok=True)
        (target / 'resources.yaml').write_text(yaml.safe_dump_all(objects))
        run('git', 'add', '.', cwd=self.checkout)
        run('git', '-c', 'user.name=Lifecycle Test', '-c', 'user.email=lifecycle@example.invalid',
            'commit', '--allow-empty', '-m', 'Update disposable fixture', cwd=self.checkout)
        run('git', 'push', 'origin', 'HEAD:main', cwd=self.checkout)
        run('git', '--git-dir', str(self.repo), 'update-server-info')
        return run('git', 'rev-parse', 'HEAD', cwd=self.checkout)

    def sync(self, name, path, objects, namespace='lifecycle-tests'):
        revision = self.commit(path, objects)
        self.apply(self.app(name, path, revision, namespace))
        def completed_revision():
            status = (self.get('application', name, 'argocd') or {}).get('status', {})
            sync = status.get('sync', {})
            # A new revision may already match live resources and need no sync
            # operation. Require its comparison result, not an older operation.
            return sync.get('status') == 'Synced' and sync.get('revision') == revision
        wait(name + ' sync at ' + revision, completed_revision)
        return revision

    def approve(self, name):
        self.k('annotate', 'application', name, '-n', 'argocd',
               'argocd.argoproj.io/deletion-approved=' + stamp(), '--overwrite')

    def delete_app(self, name):
        self.k('delete', 'application', name, '-n', 'argocd', '--wait=false')

    def observe_retained(self, kind, name, namespace=None):
        original = self.get(kind, name, namespace)
        assert original is not None, f'{kind}/{name} absent before observation'
        uid = original['metadata']['uid']
        for _ in range(5):
            current = self.get(kind, name, namespace)
            assert current and current['metadata']['uid'] == uid, f'{kind}/{name} was replaced or deleted'
            assert not current['metadata'].get('deletionTimestamp'), f'{kind}/{name} is terminating'
            time.sleep(3)
        return uid

    def deleted(self, kind, name, namespace=None):
        wait(f'{kind}/{name} deletion', lambda: self.get(kind, name, namespace) is None)

    def record(self, name, **details):
        self.report['tests'].append({'name': name, 'result': 'passed', 'observed_at': stamp(), **details})
        self.save()
        print('PASS: ' + name, flush=True)

    def save(self):
        (self.evidence / 'results.json').write_text(json.dumps(self.report, indent=2) + '\n')

    def setup(self):
        for tool in ('kind', 'docker', 'kubectl', 'helm', 'git'):
            if not shutil.which(tool):
                raise RuntimeError(f'Required tool unavailable: {tool}')
        run('kind', 'create', 'cluster', '--name', self.name, '--image', NODE,
            '--kubeconfig', str(self.kubeconfig), '--wait', '180s')
        assert self.k('config', 'current-context') == 'kind-' + self.name
        self.report['node_image'] = NODE
        self.k('create', 'namespace', 'argocd')
        self.k('create', 'namespace', 'lifecycle-tests')
        config = yaml.safe_load((ROOT / 'clusters/production/argocd/resources/kustomization.yaml').read_text())
        version = re.search(r'ref=(v[0-9.]+)$', config['resources'][0]).group(1)
        self.report['argocd_version'] = version
        self.k('apply', '--server-side', '-n', 'argocd', '-f',
               f'https://raw.githubusercontent.com/argoproj/argo-cd/{version}/manifests/install.yaml')
        # Match production tracking mode, without importing production Applications.
        self.k('patch', 'configmap', 'argocd-cm', '-n', 'argocd', '--type=merge',
               '-p', json.dumps({'data': {'application.resourceTrackingMethod': 'annotation'}}))
        self.k('rollout', 'status', 'deployment/argocd-repo-server', '-n', 'argocd', '--timeout=300s')
        self.k('rollout', 'status', 'statefulset/argocd-application-controller', '-n', 'argocd', '--timeout=300s')
        self.checkout.mkdir()
        run('git', 'init', '--bare', '--initial-branch=main', str(self.repo))
        run('git', 'init', '--initial-branch=main', str(self.checkout))
        run('git', 'remote', 'add', 'origin', str(self.repo), cwd=self.checkout)
        # Serve only synthetic, public fixtures on the isolated Docker network.
        run('docker', 'run', '-d', '--name', self.name + '-git', '--network', 'kind',
            '-v', str(self.repo) + ':/usr/share/nginx/html/fixtures.git:ro', 'nginx:1.28.0-alpine')
        ip = run('docker', 'inspect', '-f', '{{(index .NetworkSettings.Networks "kind").IPAddress}}', self.name + '-git')
        self.url = f'http://{ip}/fixtures.git'
        self.save()

    def configmap(self, name):
        return {'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': name, 'namespace': 'lifecycle-tests'},
                'data': {'value': 'disposable'}}

    def child_tests(self):
        revision = self.commit('child-data', [self.configmap('child-data')])
        child = self.app('prune-child', 'child-data', revision)
        self.sync('prune-parent', 'prune-parent', [child], 'argocd')
        wait('child workload exists', lambda: self.get('configmap', 'child-data', 'lifecycle-tests'))
        revision = self.commit('prune-parent', [])
        self.apply(self.app('prune-parent', 'prune-parent', revision, 'argocd'))
        wait('parent observes removal', lambda: (self.get('application', 'prune-parent', 'argocd') or {}).get('status', {}).get('operationState', {}).get('syncResult', {}).get('revision') == revision)
        uid = self.observe_retained('application', 'prune-child', 'argocd')
        self.approve('prune-parent')
        self.deleted('application', 'prune-child', 'argocd')
        self.deleted('configmap', 'child-data', 'lifecycle-tests')
        self.record('parent-prune-confirmation', retained_uid=uid, confirmed_deletion=True)
        self.k('annotate', 'application', 'prune-parent', '-n', 'argocd', 'argocd.argoproj.io/deletion-approved-')

        revision = self.commit('cascade-data', [self.configmap('cascade-data')])
        child = self.app('cascade-child', 'cascade-data', revision)
        project = {'apiVersion': 'argoproj.io/v1alpha1', 'kind': 'AppProject',
                   'metadata': {'name': 'cascade-project', 'namespace': 'argocd', 'annotations': {GUARD: self.guard}},
                   'spec': {'description': 'Disposable project removal gate'}}
        self.sync('cascade-parent', 'cascade-parent', [child, project], 'argocd')
        wait('cascade workload exists', lambda: self.get('configmap', 'cascade-data', 'lifecycle-tests'))
        self.delete_app('cascade-parent')
        uid = self.observe_retained('application', 'cascade-child', 'argocd')
        self.observe_retained('appproject', 'cascade-project', 'argocd')
        self.approve('cascade-parent')
        self.deleted('application', 'cascade-parent', 'argocd')
        self.deleted('application', 'cascade-child', 'argocd')
        self.deleted('appproject', 'cascade-project', 'argocd')
        self.deleted('configmap', 'cascade-data', 'lifecycle-tests')
        self.record('parent-delete-confirmation', retained_child_uid=uid, project_retained_before_approval=True)

        self.sync('direct-child', 'direct-data', [self.configmap('direct-data')])
        self.delete_app('direct-child')
        self.deleted('application', 'direct-child', 'argocd')
        self.deleted('configmap', 'direct-data', 'lifecycle-tests')
        self.record('direct-child-delete-bypasses-parent-guard', expected='child and unguarded workload deleted')

    def namespace_tests(self):
        for operation in ('prune', 'delete'):
            name = 'namespace-' + operation
            obj = {'apiVersion': 'v1', 'kind': 'Namespace', 'metadata': {'name': name, 'annotations': {GUARD: self.ns_guard}}}
            self.sync(name, name, [obj], 'argocd')
            # Not managed by this Application: proves namespace occupants survive the gate.
            self.apply({'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': 'occupant', 'namespace': name}})
            if operation == 'prune':
                revision = self.commit(name, [])
                self.apply(self.app(name, name, revision, 'argocd'))
                wait('namespace removal observed', lambda: self.get('application', name, 'argocd').get('status', {}).get('operationState', {}).get('syncResult', {}).get('revision') == revision)
            else:
                self.delete_app(name)
            uid = self.observe_retained('namespace', name)
            assert self.get('configmap', 'occupant', name)
            self.approve(name)
            self.deleted('namespace', name)
            if operation == 'prune':
                self.k('annotate', 'application', name, '-n', 'argocd', 'argocd.argoproj.io/deletion-approved-')
            self.record('namespace-' + operation + '-confirmation', retained_uid=uid, occupant_retained_before_approval=True)

    def database_tests(self):
        app = yaml.safe_load((ROOT / 'clusters/production/argocd/applications/cnpg.yaml').read_text())
        chart = next(s for s in app['spec']['sources'] if 'chart' in s)
        self.report['cnpg_chart_version'] = chart['targetRevision']
        rendered = run('helm', 'template', 'cnpg', chart['chart'], '--repo', chart['repoURL'],
                       '--version', chart['targetRevision'], '--namespace', 'cnpg-system', '--include-crds')
        self.k('create', 'namespace', 'cnpg-system')
        self.k('apply', '--server-side', '-f', '-', stdin=rendered)
        self.k('rollout', 'status', 'deployment/cnpg-cloudnative-pg', '-n', 'cnpg-system', '--timeout=300s')
        db = {'apiVersion': 'postgresql.cnpg.io/v1', 'kind': 'Cluster',
              'metadata': {'name': 'retained-db', 'namespace': 'lifecycle-tests',
                           'annotations': {GUARD: self.database['metadata']['annotations'][GUARD]}},
              'spec': {'instances': 1, 'imageName': self.database['spec']['imageName'],
                       'storage': {'size': '1Gi', 'storageClass': 'standard'}}}
        self.sync('database-owner', 'database', [db])
        wait('database ready', lambda: (self.get('cluster.postgresql.cnpg.io', 'retained-db', 'lifecycle-tests') or {}).get('status', {}).get('readyInstances') == 1, timeout=360)
        pod = 'retained-db-1'
        def sql(statement):
            return self.k('exec', '-n', 'lifecycle-tests', pod, '-c', 'postgres', '--',
                          'psql', '-U', 'postgres', '-d', 'postgres', '-At', '-c', statement)
        sql("CREATE TABLE lifecycle_evidence(value text); INSERT INTO lifecycle_evidence VALUES ('retained');")
        before = self.get('cluster.postgresql.cnpg.io', 'retained-db', 'lifecycle-tests')['metadata']['uid']
        revision = self.commit('database', [])
        self.apply(self.app('database-owner', 'database', revision))
        wait('database prune attempted', lambda: self.get('application', 'database-owner', 'argocd').get('status', {}).get('operationState', {}).get('syncResult', {}).get('revision') == revision)
        self.observe_retained('cluster.postgresql.cnpg.io', 'retained-db', 'lifecycle-tests')
        assert sql('SELECT value FROM lifecycle_evidence;') == 'retained'
        self.record('postgresql-prune-retention', retained_uid=before, query_result='retained')
        # Re-adopt before deleting its owner so both deletion paths are tested independently.
        self.sync('database-owner', 'database', [db])
        self.delete_app('database-owner')
        self.deleted('application', 'database-owner', 'argocd')
        after = self.observe_retained('cluster.postgresql.cnpg.io', 'retained-db', 'lifecycle-tests')
        assert before == after and sql('SELECT value FROM lifecycle_evidence;') == 'retained'
        self.record('postgresql-owner-deletion-retention', retained_uid=after, query_result='retained')

    def cleanup(self):
        # Only this invocation's uniquely named cluster/container can be removed.
        if shutil.which('docker'):
            run('docker', 'rm', '-f', self.name + '-git', check=False)
        if shutil.which('kind'):
            run('kind', 'delete', 'cluster', '--name', self.name, check=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args()
    args.evidence.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='gitops-lifecycle-') as directory:
        suite = Suite(directory, args.evidence)
        suite.save()
        try:
            suite.setup()
            suite.child_tests()
            suite.namespace_tests()
            suite.database_tests()
            suite.report['result'] = 'passed'
        except Exception as error:
            suite.report['result'] = 'failed'
            suite.report['error'] = str(error)
            if suite.kubeconfig.exists():
                for label, command in (('applications', ('get', 'applications', '-n', 'argocd', '-o', 'json')),
                                       ('pods', ('get', 'pods', '-A', '-o', 'wide')),
                                       ('events', ('get', 'events', '-A'))):
                    try:
                        (args.evidence / (label + '.txt')).write_text(suite.k(*command) + '\n')
                    except Exception:
                        pass
            raise
        finally:
            suite.report['finished_at'] = stamp()
            suite.save()
            suite.cleanup()


if __name__ == '__main__':
    main()

"""Git-sync guard of approved-ingest: real throwaway git repos, never the production vault."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

from test_approved_ingest import ROOT, SCRIPT, payload

# Isolate from the user's global/system git config (signing, hooks, templates).
ENV = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM='1', LC_ALL='C',
           GIT_AUTHOR_NAME='t', GIT_AUTHOR_EMAIL='t@t', GIT_COMMITTER_NAME='t', GIT_COMMITTER_EMAIL='t@t')


def second_payload():
    data = payload()
    data['source']['excerpt'] = '## Użytkownik\nDruga sprawa?\n## Asystent\nDruga odpowiedź.\n'
    data['note']['title'] = 'Druga notatka testowa'
    return data


class GitSyncGuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.origin, self.v, self.other = base / 'origin.git', base / 'vault', base / 'other'
        self.git(base, 'init', '-q', '--bare', '-b', 'main', str(self.origin))
        self.git(base, 'clone', '-q', str(self.origin), str(self.v))
        (self.v / '90-meta').mkdir()
        for f in ('schema-notatki.json', 'walidator.py'):
            shutil.copyfile(ROOT / '90-meta' / f, self.v / '90-meta' / f)
        shutil.copyfile(ROOT / 'taxonomy.md', self.v / 'taxonomy.md')
        (self.v / '90-meta/next-id').write_text('7000\n')
        (self.v / '90-meta/manifest.jsonl').write_text('')
        (self.v / 'log.md').write_text('# log\n')
        self.git(self.v, 'add', '.')
        self.git(self.v, 'commit', '-q', '-m', 'init')
        self.git(self.v, 'push', '-q', '-u', 'origin', 'main')
        self.git(self.v, 'fetch', '-q')
        self.p = base / 'approved.json'

    def git(self, cwd, *args):
        return subprocess.run(['git', *args], cwd=cwd, env=ENV, check=True,
                              capture_output=True, text=True).stdout

    def cli(self, data=None, *args):
        self.p.write_text(json.dumps(data or payload(), ensure_ascii=False))
        return subprocess.run([sys.executable, str(SCRIPT), '--vault', str(self.v), *args, str(self.p)],
                              capture_output=True, text=True, env=ENV)

    def snapshot(self):
        return {str(p.relative_to(self.v)): p.read_bytes() for p in self.v.rglob('*')
                if p.is_file() and '.git' not in p.relative_to(self.v).parts}

    def assert_refused(self, needle, data=None, *args):
        before = self.snapshot()
        result = self.cli(data, *args)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn(needle, result.stderr)
        self.assertEqual(self.snapshot(), before)

    def test_fresh_clean_clone_publishes_with_guard_ok(self):
        result = self.cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        out = json.loads(result.stdout)
        self.assertEqual(out['result'], 'published')
        self.assertEqual(out['sync'], {'git_guard': 'ok', 'upstream': 'origin/main', 'uncommitted_in_batch': 0})

    def test_failed_fetch_with_fresh_mtime_refuses(self):
        # git fetch to an unreachable remote exits 128 but still truncates and touches FETCH_HEAD.
        self.git(self.v, 'remote', 'set-url', 'origin', str(self.v.parent / 'missing.git'))
        failed = subprocess.run(['git', 'fetch', '-q', 'origin'], cwd=self.v, env=ENV, capture_output=True)
        self.assertNotEqual(failed.returncode, 0)
        self.assert_refused('does not match origin/main')
        (self.v / '.git/FETCH_HEAD').write_text('')
        self.assert_refused('does not match origin/main')

    def test_future_fetch_head_mtime_refuses(self):
        future = time.time() + 24 * 3600  # clock skew or manual touch
        os.utime(self.v / '.git/FETCH_HEAD', (future, future))
        self.assert_refused('no git fetch in the last 60 min')

    def test_tab_in_fetch_head_url_is_not_a_false_refusal(self):
        tip = self.git(self.v, 'rev-parse', 'origin/main').strip()
        (self.v / '.git/FETCH_HEAD').write_text(f"{tip}\t\tbranch 'main' of /srv/with\ttab\n")
        self.assertEqual(self.cli(None, '--check').returncode, 0)

    def test_second_remote_refuses(self):
        mirror = self.v.parent / 'mirror.git'
        self.git(self.v.parent, 'clone', '-q', '--bare', str(self.origin), str(mirror))
        self.git(self.v, 'remote', 'add', 'mirror', str(mirror))
        self.git(self.v, 'fetch', '-q', 'mirror')  # FETCH_HEAD: mirror's main at the same commit
        self.assert_refused('exactly one remote')

    def test_broken_head_is_not_reported_as_detached(self):
        (self.v / '.git/HEAD').write_text('garbage\n')
        self.assert_refused('symbolic-ref failed')

    def test_broken_vault_git_never_falls_back_to_parent_repo(self):
        parent = self.v.parent
        self.git(parent, 'init', '-q', '-b', 'main')  # a repository above the vault
        self.git(parent, 'commit', '-q', '--allow-empty', '-m', 'parent')
        (self.v / '.git/HEAD').write_text('garbage\n')
        self.assert_refused('symbolic-ref failed')

    def test_fetch_of_other_branch_does_not_count(self):
        self.git(self.v, 'push', '-q', 'origin', 'main:side')
        self.git(self.v.parent, 'clone', '-q', str(self.origin), str(self.other))
        (self.other / '90-meta/next-id').write_text('7001\n')
        self.git(self.other, 'commit', '-q', '-am', 'other machine')
        self.git(self.other, 'push', '-q')
        self.git(self.v, 'fetch', '-q', 'origin', 'side')  # fresh FETCH_HEAD, stale origin/main
        self.assert_refused('does not match origin/main')

    def test_push_since_last_fetch_requires_new_fetch(self):
        (self.v / 'README.md').write_text('x\n')
        self.git(self.v, 'add', 'README.md')
        self.git(self.v, 'commit', '-q', '-m', 'docs')
        self.git(self.v, 'push', '-q')
        self.assert_refused('git fetch origin')
        self.git(self.v, 'fetch', '-q')
        self.assertEqual(self.cli().returncode, 0)

    def test_continue_batch_never_bypasses_sync_checks(self):
        os.utime(self.v / '.git/FETCH_HEAD', (0, 0))
        self.assert_refused('git fetch', None, '--continue-batch')
        self.git(self.v, 'fetch', '-q')
        (self.v / 'log.md').write_text('# log\nlocal\n')
        self.git(self.v, 'commit', '-q', '-am', 'local only')
        self.assert_refused('git push', None, '--continue-batch')
        self.git(self.v, 'push', '-q')
        self.git(self.v.parent, 'clone', '-q', str(self.origin), str(self.other))
        (self.other / '90-meta/next-id').write_text('7001\n')
        self.git(self.other, 'commit', '-q', '-am', 'other machine')
        self.git(self.other, 'push', '-q')
        self.git(self.v, 'fetch', '-q')
        self.assert_refused('git pull', None, '--continue-batch')

    def test_inherited_git_dir_cannot_redirect_the_check(self):
        env = dict(ENV, GIT_DIR=str(self.origin))  # e.g. guard started from inside a git hook
        self.p.write_text(json.dumps(payload(), ensure_ascii=False))
        result = subprocess.run([sys.executable, str(SCRIPT), '--vault', str(self.v), '--check', str(self.p)],
                                capture_output=True, text=True, env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['sync']['git_guard'], 'ok')

    def test_missing_or_stale_fetch_refuses_without_writes(self):
        fetch_head = self.v / '.git/FETCH_HEAD'
        old = time.time() - 2 * 3600
        os.utime(fetch_head, (old, old))
        self.assert_refused('git fetch')
        self.assert_refused('git fetch', None, '--check')
        fetch_head.unlink()
        self.assert_refused('git fetch')

    def test_behind_upstream_refuses_until_pull(self):
        self.git(self.v.parent, 'clone', '-q', str(self.origin), str(self.other))
        (self.other / '90-meta/next-id').write_text('7001\n')
        self.git(self.other, 'commit', '-q', '-am', 'other machine published n-7000')
        self.git(self.other, 'push', '-q')
        self.git(self.v, 'fetch', '-q')
        self.assert_refused('git pull')
        self.git(self.v, 'pull', '-q')
        result = self.cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('n-7001', result.stdout)

    def test_unpushed_commit_on_guarded_path_refuses_until_push(self):
        (self.v / 'log.md').write_text('# log\nlocal entry\n')
        self.git(self.v, 'commit', '-q', '-am', 'local only')
        self.assert_refused('git push')
        self.git(self.v, 'push', '-q')
        self.git(self.v, 'fetch', '-q')
        self.assertEqual(self.cli().returncode, 0)

    def test_forgotten_untracked_extract_blocks_publication(self):
        (self.v / '00-archive/hermes').mkdir(parents=True)
        (self.v / '00-archive/hermes' / ('b' * 32 + '.md')).write_text('extract\n')
        self.assert_refused('--continue-batch')

    def test_forgotten_untracked_inbox_extract_blocks_publication(self):
        (self.v / '00-archive/inbox').mkdir(parents=True)
        (self.v / '00-archive/inbox' / ('b' * 32 + '.md')).write_text('extract\n')
        self.assert_refused('--continue-batch')

    def test_ignored_sensitive_extract_and_journal_do_not_block(self):
        shutil.copyfile(ROOT / '.gitignore', self.v / '.gitignore')
        self.git(self.v, 'add', '.gitignore')
        self.git(self.v, 'commit', '-q', '-m', 'real gitignore')
        self.git(self.v, 'push', '-q')
        self.git(self.v, 'fetch', '-q')
        (self.v / '00-archive/hermes/sensitive').mkdir(parents=True)
        (self.v / '00-archive/hermes/sensitive' / ('c' * 32 + '.md')).write_text('private\n')
        (self.v / '10-notes/sensitive').mkdir(parents=True)
        (self.v / '10-notes/sensitive/n-0001-private.md').write_text('private\n')
        result = self.cli(None, '--check')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['sync']['uncommitted_in_batch'], 0)

    def test_unpushed_commit_elsewhere_is_allowed(self):
        (self.v / 'README.md').write_text('x\n')
        self.git(self.v, 'add', 'README.md')
        self.git(self.v, 'commit', '-q', '-m', 'docs only')
        self.assertEqual(self.cli().returncode, 0)

    def test_batch_needs_explicit_flag_and_reruns_stay_idempotent(self):
        first = self.cli()
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assert_refused('--continue-batch', second_payload())
        self.assert_refused('--continue-batch', second_payload(), '--check')
        second = self.cli(second_payload(), '--continue-batch')
        self.assertEqual(second.returncode, 0, second.stderr)
        out = json.loads(second.stdout)
        self.assertEqual(out['notes'], ['n-7001'])
        self.assertGreater(out['sync']['uncommitted_in_batch'], 0)
        rerun = self.cli()  # no flag: verifying a published payload is never blocked
        self.assertEqual(rerun.returncode, 0, rerun.stderr)
        self.assertEqual(json.loads(rerun.stdout)['result'], 'already-done')

    def test_inherited_git_c_config_cannot_redirect_the_check(self):
        env = dict(ENV, GIT_CONFIG_PARAMETERS="'branch.main.remote'='nonexistent'")
        self.p.write_text(json.dumps(payload(), ensure_ascii=False))
        result = subprocess.run([sys.executable, str(SCRIPT), '--vault', str(self.v), '--check', str(self.p)],
                                capture_output=True, text=True, env=env)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_inherited_git_config_count_cannot_redirect_the_check(self):
        env = dict(ENV, GIT_CONFIG_COUNT='1', GIT_CONFIG_KEY_0='branch.main.remote', GIT_CONFIG_VALUE_0='nonexistent')
        self.p.write_text(json.dumps(payload(), ensure_ascii=False))
        result = subprocess.run([sys.executable, str(SCRIPT), '--vault', str(self.v), '--check', str(self.p)],
                                capture_output=True, text=True, env=env)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_other_branch_tracking_origin_main_refuses(self):
        self.git(self.v, 'checkout', '-q', '-b', 'foo', '--track', 'origin/main')
        self.assert_refused('not main')

    def test_main_without_upstream_or_tracking_other_branch_refuses(self):
        self.git(self.v, 'branch', '-q', '--unset-upstream')
        self.assert_refused('must track origin/main')
        self.git(self.v, 'push', '-q', 'origin', 'main:side')
        self.git(self.v, 'fetch', '-q')
        self.git(self.v, 'branch', '-q', '--set-upstream-to', 'origin/side')
        self.assert_refused('must track origin/main')

    def test_other_branch_without_upstream_refuses(self):
        self.git(self.v, 'checkout', '-q', '-b', 'local-experiment')
        self.assert_refused('not main')

    def test_detached_head_refuses(self):
        self.git(self.v, 'checkout', '-q', '--detach')
        self.assert_refused('detached HEAD')

    def test_vault_without_git_refuses_unless_explicit_sandbox(self):
        shutil.rmtree(self.v / '.git')
        self.assert_refused('no .git', None, '--check')
        self.p.write_text(json.dumps(payload(), ensure_ascii=False))
        result = subprocess.run([sys.executable, str(SCRIPT), '--vault', str(self.v), '--check', str(self.p)],
                                capture_output=True, text=True, env=dict(ENV, APPROVED_INGEST_ALLOW_NO_GIT='1'))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['sync'], {'git_guard': 'skipped-not-a-git-repo'})

    def test_continue_batch_cannot_be_combined_with_recovery(self):
        result = subprocess.run([sys.executable, str(SCRIPT), '--vault', str(self.v),
                                 '--continue-batch', '--recover'], capture_output=True, text=True, env=ENV)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('--continue-batch cannot be combined', result.stderr)



class RepoGitignoreTests(unittest.TestCase):
    """The vault's real .gitignore: only plain approved-ingest extracts may be tracked."""

    def test_only_plain_hermes_extracts_are_trackable(self):
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(['git', 'init', '-q', tmp], env=ENV, check=True)
            shutil.copyfile(ROOT / '.gitignore', Path(tmp) / '.gitignore')
            def ignored(path):
                return subprocess.run(['git', '-C', tmp, 'check-ignore', '-q', '--no-index', path],
                                      env=ENV).returncode == 0
            self.assertFalse(ignored('00-archive/hermes/' + 'a' * 32 + '.md'))
            self.assertFalse(ignored('00-archive/inbox/' + 'a' * 32 + '.md'))
            for path in ('00-archive/hermes/.approved-ingest-transaction.json',
                         '00-archive/inbox/sensitive/' + 'a' * 32 + '.md', '00-archive/inbox/README.md',
                         '00-archive/inbox/sub/' + 'a' * 32 + '.md', '00-archive/inbox/' + 'a' * 31 + '.md',
                         '01-inbox/2026-10/2026-10-13.md',
                         '00-archive/hermes/sensitive/' + 'a' * 32 + '.md',
                         '00-archive/hermes-desktop/session.md', '00-archive/claude/0001_x.md',
                         '00-archive/chatgpt/x.md', '00-archive/top.md', '10-notes/sensitive/n-0001-x.md', '.env',
                         '00-archive/hermes/.approved-abc123', '00-archive/hermes/sub/' + 'a' * 32 + '.md',
                         '00-archive/hermes/README.md', '00-archive/hermes/.hidden.md',
                         '00-archive/hermes/' + 'a' * 31 + '.md', '00-archive/hermes/' + 'A' * 32 + '.md'):
                with self.subTest(path=path):
                    self.assertTrue(ignored(path))

if __name__ == '__main__':
    unittest.main()

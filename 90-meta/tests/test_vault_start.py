"""vault-start.py: pull przy logowaniu tylko gdy bezpiecznie, na jednorazowych repo gita."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from test_git_sync_guard import ENV

SCRIPT = Path(__file__).resolve().parents[1] / 'hermes/vault-start.py'


class VaultStartTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.origin, self.v, self.other = base / 'origin.git', base / 'vault', base / 'other'
        self.git(base, 'init', '-q', '--bare', '-b', 'main', str(self.origin))
        self.git(base, 'clone', '-q', str(self.origin), str(self.v))
        (self.v / 'a.md').write_text('a\n')
        (self.v / '.gitignore').write_text('01-inbox/\n')
        self.git(self.v, 'add', '.')
        self.git(self.v, 'commit', '-q', '-m', 'init')
        self.git(self.v, 'push', '-q', '-u', 'origin', 'main')
        self.git(base, 'clone', '-q', str(self.origin), str(self.other))

    def git(self, cwd, *args):
        return subprocess.run(['git', *args], cwd=cwd, env=ENV, check=True, capture_output=True, text=True).stdout

    def push_from_other(self):
        (self.other / 'b.md').write_text('b\n')
        self.git(self.other, 'add', 'b.md')
        self.git(self.other, 'commit', '-q', '-m', 'b')
        self.git(self.other, 'push', '-q')

    def run_it(self):
        r = subprocess.run([sys.executable, str(SCRIPT), '--vault', str(self.v), '--bez-powiadomien', '--proby', '1'],
                           capture_output=True, text=True, env=ENV)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def head(self):
        return self.git(self.v, 'rev-parse', 'HEAD')

    def test_clean_and_behind_pulls(self):
        self.push_from_other()
        out = self.run_it()
        self.assertIn('pobrano 1 commit,', out)
        self.assertTrue((self.v / 'b.md').exists())

    def test_up_to_date_is_silent_apart_from_log(self):
        self.assertEqual(self.run_it().strip(), 'vault aktualny')

    def test_dirty_tracked_file_skips_pull(self):
        self.push_from_other()
        (self.v / 'a.md').write_text('zmiana\n')
        before = self.head()
        out = self.run_it()
        self.assertIn('1 niezacommitowana zmiana', out)
        self.assertIn('pull pominięty, na GitHubie czeka: 1 commit', out)
        self.assertEqual(self.head(), before)
        self.assertEqual((self.v / 'a.md').read_text(), 'zmiana\n')

    def test_unpushed_commit_is_reported_and_not_merged(self):
        self.push_from_other()
        (self.v / 'c.md').write_text('c\n')
        self.git(self.v, 'add', 'c.md')
        self.git(self.v, 'commit', '-q', '-m', 'c')
        before = self.head()
        out = self.run_it()
        self.assertIn('1 commit niewypchnięty', out)
        self.assertEqual(self.head(), before)

    def test_journal_blocks_pull(self):
        self.push_from_other()
        (self.v / '90-meta').mkdir()
        (self.v / '90-meta/.approved-status-transaction.json').write_text('{}')
        before = self.head()
        self.assertIn('przerwana transakcja', self.run_it())
        self.assertEqual(self.head(), before)

    def test_unreachable_origin_and_inbox_count(self):
        self.git(self.v, 'remote', 'set-url', 'origin', str(self.v.parent / 'missing.git'))
        (self.v / '01-inbox/2026-10').mkdir(parents=True)
        (self.v / '01-inbox/2026-10/2026-10-14.md').write_text('# 2026-10-14\n\n## 10:00\nx\n\n## 11:00\ny\n')
        out = self.run_it()
        self.assertIn('brak połączenia z GitHubem', out)
        self.assertIn('inbox: 2 wpisy czekają', out)


if __name__ == '__main__':
    unittest.main()

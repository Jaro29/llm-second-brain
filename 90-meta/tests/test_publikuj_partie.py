"""publikuj-partie.py: cała partia w jednym przebiegu, na prawdziwych jednorazowych repo gita."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from test_approved_ingest import ROOT, payload
from test_approved_status import status_payload
from test_git_sync_guard import ENV

SCRIPT = ROOT / '90-meta/publikuj-partie.py'
TOOLS = ('approved-ingest.py', 'approved-status.py', 'walidator.py', 'compile.py', 'otwarte-watki.py',
         'inbox-sprzatanie.py', 'schema-notatki.json')
INBOX_ENTRY = '## 12:51\nDesktop, Linux, sesja graficzna: test partii z inboxu.\n'


def ingest(n, inbox=False):
    data = payload()
    data['note']['title'] = f'Notatka partii {n}'
    data['note']['status'] = 'unresolved'
    data['source']['excerpt'] = f'## Użytkownik\nSprawa {n}?\n## Asystent\nOdpowiedź {n}.\n'
    if inbox:
        data['source'].update(application='inbox', models=[], date='2026-10-13', excerpt=INBOX_ENTRY,
                              conversation_id='01-inbox/2026-10/2026-10-13.md#12:51')
    return data


class PublikujPartieTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.base, self.origin, self.v = base, base / 'origin.git', base / 'vault'
        self.git(base, 'init', '-q', '--bare', '-b', 'main', str(self.origin))
        self.git(base, 'clone', '-q', str(self.origin), str(self.v))
        (self.v / '90-meta').mkdir()
        (self.v / '30-state').mkdir()
        (self.v / '30-state/otwarte-watki.md').write_text('')
        for f in TOOLS:
            shutil.copyfile(ROOT / '90-meta' / f, self.v / '90-meta' / f)
        for f in ('taxonomy.md', '.gitignore'):
            shutil.copyfile(ROOT / f, self.v / f)
        (self.v / '90-meta/next-id').write_text('7000\n')
        (self.v / '90-meta/manifest.jsonl').write_text('')
        (self.v / 'log.md').write_text('# log\n')
        self.git(self.v, 'add', '.')
        self.git(self.v, 'commit', '-q', '-m', 'init')
        self.git(self.v, 'push', '-q', '-u', 'origin', 'main')
        self.n = 0

    def git(self, cwd, *args):
        return subprocess.run(['git', *args], cwd=cwd, env=ENV, check=True, capture_output=True, text=True).stdout

    def files(self, *datas):
        out = []
        for d in datas:
            self.n += 1
            p = self.base / f'p{self.n}.json'
            p.write_text(json.dumps(d, ensure_ascii=False))
            out.append(str(p))
        return out

    def cli(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), '--vault', str(self.v), *args],
                              capture_output=True, text=True, env=ENV)

    def snapshot(self):
        return {str(p.relative_to(self.v)): p.read_bytes() for p in self.v.rglob('*')
                if p.is_file() and '.git' not in p.relative_to(self.v).parts}

    def origin_ls(self):
        return self.git(self.v, '-c', 'core.quotePath=false', 'ls-tree', '-r', '--name-only', 'origin/main')

    def test_mixed_batch_is_published_committed_pushed_and_inbox_cleaned(self):
        r = self.cli(*self.files(ingest(0)))
        self.assertEqual(r.returncode, 0, r.stderr)
        inbox = self.v / '01-inbox/2026-10/2026-10-13.md'
        inbox.parent.mkdir(parents=True)
        inbox.write_text('# 2026-10-13\n\n' + INBOX_ENTRY)
        r = self.cli('-m', 'test', *self.files(ingest(1, inbox=True), status_payload(note='n-7000')))
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual([i['result'] for i in out['items']], ['published', 'published'])
        self.assertEqual(self.git(self.v, 'status', '--porcelain'), '')
        self.assertEqual(self.git(self.v, 'rev-parse', 'HEAD'), self.git(self.v, 'rev-parse', 'origin/main'))
        listed = self.origin_ls()
        self.assertIn('n-7001-notatka-partii-1.md', listed)
        self.assertRegex(listed, r'00-archive/inbox/[0-9a-f]{32}\.md')
        self.assertIn('index.md', listed)
        self.assertIn('status: resolved', self.git(self.v, 'show', 'origin/main:' + next(
            l for l in listed.splitlines() if '/n-7000-' in l)))
        self.assertIn('publikuj-partie: test;', self.git(self.v, 'log', '-1', '--format=%s'))
        self.assertFalse(inbox.exists(), 'processed inbox entry must be cleaned up')
        self.assertIn('usunięto: 1', out['inbox'])

    def test_check_writes_nothing(self):
        before = self.snapshot()
        r = self.cli('--check', *self.files(ingest(0), ingest(1)))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)['result'], 'validated-not-published')
        self.assertEqual(self.snapshot(), before)

    def test_invalid_payload_anywhere_means_nothing_is_written(self):
        bad = ingest(1)
        bad['note']['domains'] = ['wymyslona']
        before = self.snapshot()
        r = self.cli(*self.files(ingest(0), bad))
        self.assertEqual(r.returncode, 1)
        self.assertIn('--check odrzucił', r.stderr)
        self.assertEqual(self.snapshot(), before)

    def test_dirty_batch_paths_refused_then_resumed_with_wznow(self):
        first, second = self.files(ingest(0), ingest(1))
        # Przerwana partia: pierwszy payload opublikowany, ale niezacommitowany.
        self.git(self.v, 'fetch', '-q')
        subprocess.run([sys.executable, str(self.v / '90-meta/approved-ingest.py'), '--vault', str(self.v), first],
                       check=True, capture_output=True, env=ENV)
        r = self.cli(first, second)
        self.assertEqual(r.returncode, 1)
        self.assertIn('--wznow', r.stderr)
        r = self.cli('--wznow', first, second)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual([i['result'] for i in json.loads(r.stdout)['items']], ['already-done', 'published'])
        self.assertEqual(self.git(self.v, 'status', '--porcelain'), '')
        self.assertIn('n-7001-notatka-partii-1.md', self.origin_ls())

    def test_rejected_push_exits_3_with_local_commit(self):
        self.git(self.v, 'remote', 'set-url', '--push', 'origin', str(self.base / 'missing.git'))
        r = self.cli(*self.files(ingest(0)))
        self.assertEqual(r.returncode, 3, r.stderr)
        self.assertIn('push odrzucony', r.stderr)
        self.assertIn('publikuj-partie', self.git(self.v, 'log', '-1', '--format=%s'))
        self.assertNotIn('n-7000', self.origin_ls())


if __name__ == '__main__':
    unittest.main()

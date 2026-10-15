"""approved-status acceptance tests: all writes confined to temporary vaults."""
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[2]
INGEST = ROOT / '90-meta/approved-ingest.py'
STATUS = ROOT / '90-meta/approved-status.py'


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def ingest_payload(n, status='unresolved', entities=('Java',)):
    return {'approval': 'approved', 'source': {
        'application': 'hermes', 'models': [], 'conversation_id': f'session-{n}', 'date': '2026-10-14',
        'lang': 'pl', 'excerpt': f'## Użytkownik\nPytanie numer {n}?\n## Asystent\nOdpowiedź {n}.\n'},
        'note': dict(title=f'Notatka testowa {n}', summary='Streszczenie operacyjne notatki testowej, wystarczająco '
                     'długie, żeby walidator je przyjął bez zastrzeżeń.',
                     domains=['java'], kind='troubleshooting', projects=[], status=status, signal=3,
                     sensitive=False, entities=list(entities), question=f'Pytanie {n}?', outcome='Wynik.',
                     has_code=False, code_langs=[], segment_of='1/1', turns='1', kontekst='Kontekst.',
                     rozwiazanie='Rozwiązanie.', kod='', pulapki=f'Pułapka {n}.', decyzje='',
                     superseded_by='', confidence=1.0)}


def status_payload(note='n-7000', status='resolved', superseded_by='', powod='Sprawa rozwiązana w nowszej notatce.'):
    return {'approval': 'approved', 'note': note, 'status': status, 'superseded_by': superseded_by, 'powod': powod}


class StatusTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.dict(os.environ, {'APPROVED_INGEST_ALLOW_NO_GIT': '1'}))
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.v = Path(self.tmp.name) / 'vault'
        (self.v / '90-meta').mkdir(parents=True)
        for f in ('schema-notatki.json', 'walidator.py', 'compile.py'):
            shutil.copyfile(ROOT / '90-meta' / f, self.v / '90-meta' / f)
        shutil.copyfile(ROOT / 'taxonomy.md', self.v / 'taxonomy.md')
        (self.v / '90-meta/next-id').write_text('7000\n')
        (self.v / '90-meta/manifest.jsonl').write_text('')
        self.p = Path(self.tmp.name) / 'payload.json'
        self.ingested = []
        for n in range(2):
            self.ingest(ingest_payload(n))

    def ingest(self, data):
        self.p.write_text(json.dumps(data, ensure_ascii=False))
        r = subprocess.run([sys.executable, str(INGEST), '--vault', str(self.v), '--continue-batch', str(self.p)],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.ingested.append(data)
        return r

    def cli(self, data, *args):
        self.p.write_text(json.dumps(data, ensure_ascii=False))
        return subprocess.run([sys.executable, str(STATUS), '--vault', str(self.v), '--continue-batch', *args,
                               str(self.p)], capture_output=True, text=True)

    def note(self, note_id):
        return next(self.v.glob(f'10-notes/{note_id}-*.md'))

    def meta(self, note_id):
        return yaml.safe_load(self.note(note_id).read_text().split('\n---\n')[0][4:])

    def snapshot(self):
        return {str(p.relative_to(self.v)): p.read_bytes() for p in self.v.rglob('*') if p.is_file()}

    def walidator(self):
        return subprocess.run([sys.executable, str(self.v / '90-meta/walidator.py')], capture_output=True, text=True)

    def test_resolved_changes_only_status_line_and_appends_manifest_and_log(self):
        before = self.note('n-7000').read_text()
        r = self.cli(status_payload())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)['result'], 'published')
        after = self.note('n-7000').read_text()
        diff = [(a, b) for a, b in zip(before.splitlines(), after.splitlines()) if a != b]
        self.assertEqual(diff, [('status: unresolved', 'status: resolved')])
        rows = [json.loads(line) for line in (self.v / '90-meta/manifest.jsonl').read_text().splitlines()]
        self.assertEqual(len(rows), 3)
        self.assertEqual({k: rows[-1][k] for k in ('kind', 'note', 'from', 'to', 'superseded_by')},
                         {'kind': 'status', 'note': 'n-7000', 'from': 'unresolved', 'to': 'resolved',
                          'superseded_by': None})
        self.assertEqual(rows[-1]['note_sha256'], hashlib.sha256(after.encode()).hexdigest())
        self.assertIn('approved-status', (self.v / 'log.md').read_text().splitlines()[-1])
        self.assertEqual(self.walidator().returncode, 0)

    def test_superseded_sets_both_fields_and_rerun_is_idempotent(self):
        data = status_payload(status='superseded', superseded_by='n-7001')
        self.assertEqual(self.cli(data).returncode, 0)
        m = self.meta('n-7000')
        self.assertEqual((m['status'], m['superseded_by']), ('superseded', 'n-7001'))
        snap = self.snapshot()
        r = self.cli(data)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)['result'], 'already-done')
        self.assertEqual(self.snapshot(), snap)
        self.assertEqual(self.walidator().returncode, 0)

    def test_check_writes_nothing(self):
        snap = self.snapshot()
        r = self.cli(status_payload(), '--check')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)['result'], 'validated-not-published')
        self.assertEqual(self.snapshot(), snap)

    def test_invalid_payloads_are_refused_without_writes(self):
        cases = {'superseded without target': status_payload(status='superseded'),
                 'resolved with target': status_payload(superseded_by='n-7001'),
                 'self reference': status_payload(status='superseded', superseded_by='n-7000'),
                 'missing target': status_payload(status='superseded', superseded_by='n-7999'),
                 'missing note': status_payload(note='n-7999'),
                 'unknown status': status_payload(status='active'),
                 'short reason': status_payload(powod='bo tak'),
                 'credential in reason': status_payload(powod='klucz ghp_' + 'A' * 30 + ' wyciekł'),
                 'no approval': dict(status_payload(), approval='maybe'),
                 'extra field': dict(status_payload(), title='x')}
        for name, data in cases.items():
            with self.subTest(name):
                snap = self.snapshot()
                r = self.cli(data)
                self.assertNotEqual(r.returncode, 0, r.stdout)
                self.assertEqual(self.snapshot(), snap)

    def test_superseded_note_is_final_and_cannot_be_a_target(self):
        self.assertEqual(self.cli(status_payload(status='superseded', superseded_by='n-7001')).returncode, 0)
        for data in (status_payload(), status_payload(note='n-7001', status='superseded', superseded_by='n-7000')):
            with self.subTest(data=data):
                snap = self.snapshot()
                self.assertNotEqual(self.cli(data).returncode, 0)
                self.assertEqual(self.snapshot(), snap)

    def test_same_status_is_refused(self):
        self.assertEqual(self.cli(status_payload()).returncode, 0)
        r = self.cli(status_payload(powod='Drugi raz to samo, inny powód.'))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('already has status', r.stderr)

    def test_original_ingest_rerun_accepts_status_change_but_detects_manual_edit(self):
        self.assertEqual(self.cli(status_payload()).returncode, 0)
        self.p.write_text(json.dumps(self.ingested[0], ensure_ascii=False))
        rerun = lambda: subprocess.run([sys.executable, str(INGEST), '--vault', str(self.v), str(self.p)],
                                       capture_output=True, text=True)
        r = rerun()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)['result'], 'already-done')
        note = self.note('n-7000')
        note.write_text(note.read_text() + '\nręczna zmiana\n')
        r = rerun()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('note drift', r.stderr)

    def test_failed_publication_rolls_back_and_blocks_ingest_until_recover(self):
        mod = load(STATUS, 'approved_status_test')
        snap = self.snapshot()
        real = mod.ai.atomic_write

        def failing(target, content):
            if Path(target).name == 'log.md':
                raise OSError('disk full')
            return real(target, content)
        with patch.object(mod.ai, 'atomic_write', failing):
            with self.assertRaises(OSError):
                mod.change(self.v.resolve(), status_payload(), continue_batch=True)
        self.assertEqual(self.snapshot(), snap)
        # A journal left behind (crash before rollback) blocks both scripts until --recover.
        files, _, _ = mod.prepare(self.v.resolve(), status_payload())
        entries = {name: {'before': base64.b64encode((self.v / name).read_bytes()).decode()
                          if (self.v / name).exists() else None,
                          'after': base64.b64encode(text.encode()).decode()} for name, text in files.items()}
        (self.v / mod.JOURNAL).write_text(json.dumps({'entries': entries}))
        for name, text in files.items():
            if name.startswith('10-notes/'):
                (self.v / name).write_text(text)
        self.p.write_text(json.dumps(ingest_payload(5), ensure_ascii=False))
        r = subprocess.run([sys.executable, str(INGEST), '--vault', str(self.v), '--continue-batch', str(self.p)],
                           capture_output=True, text=True)
        self.assertIn('approved-status.py --recover', r.stderr)
        self.assertNotEqual(self.cli(status_payload()).returncode, 0)
        r = subprocess.run([sys.executable, str(STATUS), '--vault', str(self.v), '--recover'],
                           capture_output=True, text=True)
        self.assertEqual(json.loads(r.stdout)['result'], 'rolled-back')
        self.assertEqual(self.snapshot(), snap)

    def test_source_archive_missing_on_this_clone_does_not_block_status_change(self):
        # 00-archive/ (poza gitem) bywa niepełne na innym klonie; zmiana statusu go nie dotyczy.
        source = self.v / self.meta('n-7000')['source']['file']
        source.unlink()
        r = self.cli(status_payload(), '--check')
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(out['validation']['unavailable_sources'], [str(source.relative_to(self.v))])
        r = self.cli(status_payload())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.meta('n-7000')['status'], 'resolved')
        self.assertFalse(source.exists(), 'placeholder must stay in staging, never in the vault')

    def test_walidator_rejects_dangling_superseded_by(self):
        note = self.note('n-7000')
        note.write_text(note.read_text().replace('status: unresolved', 'status: superseded')
                        .replace('superseded_by: null', 'superseded_by: n-7999'))
        r = self.walidator()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('takiej notatki nie ma', r.stdout)

    def test_compile_marks_superseded_and_drops_its_pitfalls(self):
        # Pages need an entity below the 20% ceiling: pad the corpus with unrelated notes.
        for n in range(2, 12):
            self.ingest(ingest_payload(n, entities=(f'Inne{n}',)))
        for note_id in ('n-7000', 'n-7001'):
            f = self.note(note_id)
            f.write_text(f.read_text().replace('entities: [Java]', 'entities: [Alfa]'))
        self.assertEqual(self.cli(status_payload(status='superseded', superseded_by='n-7001')).returncode, 0)
        (self.v / '20-wiki').mkdir()
        r = subprocess.run([sys.executable, str(self.v / '90-meta/compile.py'), '2'], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        page = (self.v / '20-wiki/alfa.md').read_text()
        self.assertIn('~~[[n-7000-notatka-testowa-0|Notatka testowa 0]]~~', page)
        self.assertIn('zastąpione przez [[n-7001-notatka-testowa-1|n-7001]]', page)
        self.assertNotIn('Pułapka 0.', page)
        self.assertIn('Pułapka 1.', page)


if __name__ == '__main__':
    unittest.main()

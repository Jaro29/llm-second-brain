"""Approved ingest acceptance tests: all writes confined to temporary vaults."""
import base64
import fcntl
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / '90-meta/approved-ingest.py'


def payload():
    return {'approval': 'approved', 'source': {
        'application': 'hermes', 'models': ['test-model'],
        'conversation_id': 'session-example', 'date': '2026-09-19', 'lang': 'pl',
        'excerpt': '## Użytkownik\nJak naprawić test?\n## Asystent\nPopraw konfigurację.\n'},
        'note': dict(title='Naprawa testu', summary='Test działa po poprawieniu konfiguracji środowiska. '
                    'Wcześniejsza konfiguracja powodowała błąd uruchomienia.',
                    domains=['java'], kind='troubleshooting', projects=[], status='resolved',
                    signal=3, sensitive=False, entities=['Java'], question='Jak naprawić test?',
                    outcome='Test działa.', has_code=False, code_langs=[], segment_of='1/1',
                    turns='1', kontekst='Błąd testu.', rozwiazanie='Poprawiono konfigurację.',
                    kod='', pulapki='Zła konfiguracja.', decyzje='',
                    superseded_by='', confidence=1.0)}


class ApprovedTests(unittest.TestCase):
    def setUp(self):
        # Sandbox vaults have no .git: the git-sync guard is tested in test_git_sync_guard.py.
        self.enterContext(patch.dict(os.environ, {'APPROVED_INGEST_ALLOW_NO_GIT': '1'}))
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.v = Path(self.tmp.name) / 'vault'
        (self.v / '90-meta').mkdir(parents=True)
        for f in ('schema-notatki.json', 'walidator.py'):
            shutil.copyfile(ROOT / '90-meta' / f, self.v / '90-meta' / f)
        shutil.copyfile(ROOT / 'taxonomy.md', self.v / 'taxonomy.md')
        (self.v / '90-meta/next-id').write_text('7000\n')
        (self.v / '90-meta/manifest.jsonl').write_text('')
        self.p = Path(self.tmp.name) / 'approved.json'
        self.data = payload()

    def cli(self, *args):
        self.p.write_text(json.dumps(self.data, ensure_ascii=False))
        return subprocess.run([sys.executable, str(SCRIPT), '--vault', str(self.v),
                               *args, str(self.p)], capture_output=True, text=True)

    def snapshot(self):
        return {str(p.relative_to(self.v)): p.read_bytes() for p in self.v.rglob('*') if p.is_file()}

    def test_invalid_payload_is_rejected_before_any_publication(self):
        cases = [('domains', ['invented']), ('kind', 'invented'), ('projects', ['invented']),
                 ('status', 'invented'), ('signal', 1), ('summary', 'short'),
                 ('sensitive', False)]
        for key, value in cases:
            with self.subTest(key=key):
                self.data = payload()
                self.data['note'][key] = value
                if key == 'sensitive':
                    self.data['note']['domains'] = ['zdrowie']
                before = self.snapshot()
                result = self.cli()
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertEqual(self.snapshot(), before)
        for key, value in [('application', 'claude'), ('excerpt', ''), ('date', 'bad'),
                           ('models', 'model'), ('conversation_id', '')]:
            with self.subTest(source=key):
                self.data = payload()
                self.data['source'][key] = value
                before = self.snapshot()
                result = self.cli()
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertEqual(self.snapshot(), before)

    def test_staged_validator_blocks_invalid_rendered_note(self):
        self.data['note']['status'] = 'superseded'
        before = self.snapshot()
        result = self.cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('superseded', result.stderr)
        self.assertEqual(self.snapshot(), before)

    def test_rerun_is_noop_and_conflicting_approval_does_not_allocate_id(self):
        self.assertEqual(self.cli().returncode, 0)
        before = self.snapshot()
        result = self.cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('already-done', result.stdout)
        self.assertEqual(self.snapshot(), before)
        self.data['note']['rozwiazanie'] = 'Different approved text'
        result = self.cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('conflict', result.stderr)
        self.assertEqual(self.snapshot(), before)

    def test_live_lock_blocks_without_writes(self):
        fd = os.open(self.v / '90-meta', os.O_RDONLY)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            before = self.snapshot()
            result = self.cli()
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('locked', result.stderr)
            self.assertEqual(self.snapshot(), before)
        finally:
            os.close(fd)

    def test_mid_publication_failure_rolls_back_all_files(self):
        module = runpy.run_path(str(SCRIPT))
        before = self.snapshot()
        real_replace = os.replace
        def fail_counter(src, dst):
            if Path(dst) == self.v / '90-meta/next-id':
                raise OSError('simulated disk failure')
            return real_replace(src, dst)
        with patch('os.replace', side_effect=fail_counter):
            with self.assertRaisesRegex(OSError, 'simulated disk failure'):
                module['ingest'](self.v, self.data)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.cli().returncode, 0)

    def test_sensitive_mid_publication_failure_rolls_back(self):
        self.data['note'].update(domains=['zdrowie'], sensitive=True)
        module = runpy.run_path(str(SCRIPT))
        before = self.snapshot()
        real_replace = os.replace
        def fail_counter(src, dst):
            if Path(dst) == self.v / '90-meta/next-id':
                raise OSError('simulated disk failure')
            return real_replace(src, dst)
        with patch('os.replace', side_effect=fail_counter):
            with self.assertRaisesRegex(OSError, 'simulated disk failure'):
                module['ingest'](self.v, self.data)
        self.assertEqual(self.snapshot(), before)

    def test_failed_rollback_leaves_recoverable_journal_and_blocks_ingest(self):
        module = runpy.run_path(str(SCRIPT))
        before = self.snapshot()
        real_replace = os.replace
        manifest_writes = 0
        def fail_commit_and_rollback(src, dst):
            nonlocal manifest_writes
            if Path(dst) == self.v / '90-meta/next-id':
                raise OSError('counter unavailable')
            if Path(dst) == self.v / '90-meta/manifest.jsonl':
                manifest_writes += 1
                if manifest_writes > 1:
                    raise OSError('rollback unavailable')
            return real_replace(src, dst)
        with patch('os.replace', side_effect=fail_commit_and_rollback):
            with self.assertRaisesRegex(Exception, 'recovery required'):
                module['ingest'](self.v, self.data)
        journal = self.v / '00-archive/hermes/.approved-ingest-transaction.json'
        self.assertTrue(journal.exists())
        damaged = self.snapshot()
        blocked = self.cli()
        self.assertNotEqual(blocked.returncode, 0)
        self.assertIn('recovery required', blocked.stderr)
        self.assertEqual(self.snapshot(), damaged)
        recovered = subprocess.run([sys.executable, str(SCRIPT), '--vault', str(self.v), '--recover'],
                                   capture_output=True, text=True)
        self.assertEqual(recovered.returncode, 0, recovered.stderr)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.cli().returncode, 0)

    def test_check_reports_unavailable_legacy_sources_without_writing(self):
        row = {'file': '00-archive/claude/missing.md', 'content_hash': 'sha256:legacy',
               'status': 'done', 'notes': ['n-0001']}
        (self.v / '90-meta/manifest.jsonl').write_text(json.dumps(row) + '\n')
        before = self.snapshot()
        result = self.cli('--check')
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report['result'], 'validated-not-published')
        self.assertEqual(report['validation']['scope'], 'approved-note-only')
        self.assertEqual(report['validation']['unavailable_sources'], ['00-archive/claude/missing.md'])
        self.assertFalse(report['validation']['full_vault_validated'])
        self.assertEqual(self.snapshot(), before)

    def test_stale_counter_cannot_reuse_reserved_or_existing_ids(self):
        for location in ('manifest', 'note'):
            with self.subTest(location=location):
                manifest = self.v / '90-meta/manifest.jsonl'
                manifest.write_text('')
                note = self.v / '10-notes/n-7000-existing.md'
                note.parent.mkdir(exist_ok=True)
                note.unlink(missing_ok=True)
                if location == 'manifest':
                    manifest.write_text(json.dumps({'file': '00-archive/missing', 'notes': ['n-7000'],
                                                    'content_hash': 'legacy', 'status': 'done'}) + '\n')
                else:
                    note.write_text('Existing note must survive')
                before = self.snapshot()
                result = self.cli()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('next-id', result.stderr)
                self.assertEqual(self.snapshot(), before)

    def test_archive_collision_or_symlink_never_overwrites_source(self):
        module = runpy.run_path(str(SCRIPT))
        archive = self.v / ('00-archive/hermes/' + module['content_hash'](self.data['source']['excerpt']).split(':')[1] + '.md')
        archive.parent.mkdir(parents=True)
        archive.write_text('Unrelated existing source')
        before = self.snapshot()
        result = self.cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.snapshot(), before)
        archive.unlink()
        external = Path(self.tmp.name) / 'external'
        external.mkdir()
        (self.v / '10-notes').symlink_to(external, target_is_directory=True)
        result = self.cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('symlink', result.stderr)
        self.assertEqual(list(external.iterdir()), [])
        self.assertFalse(archive.exists())

    def test_rerun_refuses_missing_source_or_drift_in_published_note(self):
        self.assertEqual(self.cli().returncode, 0)
        row = json.loads((self.v / '90-meta/manifest.jsonl').read_text())
        archive = self.v / row['file']
        original = archive.read_bytes()
        archive.unlink()
        before = self.snapshot()
        result = self.cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('unavailable-source', result.stderr)
        self.assertEqual(self.snapshot(), before)
        archive.write_bytes(original)
        note = next(self.v.glob('10-notes/**/*.md'))
        note.write_text(note.read_text() + '\nHuman edit\n')
        before = self.snapshot()
        result = self.cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('drift', result.stderr)
        self.assertEqual(self.snapshot(), before)

    def test_manifest_prefix_bytes_are_preserved_even_without_final_newline(self):
        manifest = self.v / '90-meta/manifest.jsonl'
        row = json.dumps({'file': '00-archive/legacy/missing.md', 'notes': [], 'content_hash': 'legacy'})
        original = (row + '\r\n' + row.replace('legacy', 'older')).encode()
        manifest.write_bytes(original)
        result = self.cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        after = manifest.read_bytes()
        self.assertTrue(after.startswith(original + b'\n'))
        self.assertEqual(len([json.loads(line) for line in after.splitlines()]), 3)
        self.assertEqual(self.cli().returncode, 0)

    def test_recovery_rejects_journal_paths_outside_transaction_scope(self):
        for name in ('../outside', '30-state/identity.md'):
            target = self.v / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b'preserve')
            journal = self.v / '00-archive/hermes/.approved-ingest-transaction.json'
            journal.parent.mkdir(parents=True, exist_ok=True)
            journal.write_text(json.dumps({'entries': {name: {'before': None,
                'after': base64.b64encode(b'preserve').decode()}}}))
            result = subprocess.run([sys.executable, str(SCRIPT), '--vault', str(self.v), '--recover'],
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(target.read_bytes(), b'preserve')
            self.assertTrue(journal.exists())

    def test_new_identity_sections_are_rejected_not_silently_rewritten(self):
        self.data['note']['rozwiazanie'] = '## Sygnały o mnie\nNie publikuj profilu.'
        before = self.snapshot()
        result = self.cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('identity', result.stderr)
        self.assertEqual(self.snapshot(), before)

    def test_preserves_seven_sections_related_and_unknown_confidence(self):
        self.data['note'].update(related=['n-0048'], confidence=None,
                                 zrodlo='Original session and approval message 1131, 1147.')
        result = self.cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        text = next(self.v.glob('10-notes/**/*.md')).read_text()
        fm = yaml.safe_load(text.split('---')[1])
        self.assertEqual(fm['related'], ['n-0048'])
        self.assertIsNone(fm['confidence'])
        self.assertEqual([s for s in text.splitlines() if s.startswith('## ')],
                         ['## Kontekst', '## Pytanie', '## Rozwiązanie', '## Kod',
                          '## Pułapki i uwagi', '## Decyzje', '## Źródło'])
        self.assertIn(self.data['note']['zrodlo'], text)

    def test_secret_candidates_rejected_without_echoing_payload(self):
        secret = 'sk-' + 'aB2c' * 12
        self.data['source']['excerpt'] += '\nAPI key: ' + secret
        before = self.snapshot()
        result = self.cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn(secret, result.stderr + result.stdout)
        self.assertEqual(self.snapshot(), before)

    def test_invalid_schema_does_not_dump_private_content(self):
        private = 'PRIVATE_SENTINEL_DO_NOT_LOG'
        self.data['note']['summary'] = private
        result = self.cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn(private, result.stderr + result.stdout)

    def test_one_run_log_entry_has_canonical_format_and_rerun_is_idempotent(self):
        log = self.v / 'log.md'
        log.write_bytes(b'# Existing log\r\n')
        before = log.read_bytes()
        self.assertEqual(self.cli('--check').returncode, 0)
        self.assertEqual(log.read_bytes(), before)
        self.assertEqual(self.cli().returncode, 0)
        after = log.read_bytes()
        row = json.loads((self.v / '90-meta/manifest.jsonl').read_text())
        entry = (f'## [{row["processed_at"][:10]}] approved-ingest | '
                 f'{row["processed_at"]} approved-1.0: published n-7000; '
                 'offline approved Import/Ingest.\n').encode()
        self.assertEqual(after, before + b'\n' + entry)
        self.assertEqual(after.count(b'\n## ['), 1)
        self.assertEqual(self.cli().returncode, 0)
        self.assertEqual(log.read_bytes(), after)

    def test_check_cannot_be_combined_with_recovery(self):
        result = subprocess.run([sys.executable, str(SCRIPT), '--vault', str(self.v),
                                 '--check', '--recover'], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)

    def test_cli_publishes_exact_approved_content_with_source_and_counter(self):
        result = self.cli()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        notes = list(self.v.glob('10-notes/**/*.md'))
        self.assertEqual(len(notes), 1)
        text = notes[0].read_text()
        fm = yaml.safe_load(text.split('---')[1])
        self.assertEqual(fm['id'], 'n-7000')
        self.assertEqual(fm['summary'], self.data['note']['summary'])
        self.assertIn('\nPoprawiono konfigurację.\n', text)
        self.assertNotIn('Sygnały o mnie', text)
        self.assertEqual(fm['source']['application'], 'hermes')
        self.assertEqual(fm['source']['models'], ['test-model'])
        self.assertNotEqual(fm['source'].get('model'), 'hermes')
        self.assertEqual((self.v / fm['source']['file']).read_text(), self.data['source']['excerpt'])
        row = json.loads((self.v / '90-meta/manifest.jsonl').read_text())
        self.assertEqual(row['notes'], ['n-7000'])
        self.assertEqual(row['file'], fm['source']['file'])
        self.assertEqual(row['content_hash'], fm['content_hash'])
        self.assertEqual((self.v / '90-meta/next-id').read_text(), '7001\n')
        checked = subprocess.run([sys.executable, str(self.v / '90-meta/walidator.py')],
                                 capture_output=True, text=True)
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)


    def test_sensitive_extract_goes_to_ignored_subdirectory(self):
        self.data['note'].update(domains=['zdrowie'], sensitive=True)
        result = self.cli()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        row = json.loads((self.v / '90-meta/manifest.jsonl').read_text())
        self.assertRegex(row['file'], r'^00-archive/hermes/sensitive/[0-9a-f]{32}\.md$')
        self.assertTrue(row['note_file'].startswith('10-notes/sensitive/'))
        self.assertEqual((self.v / row['file']).read_text(), self.data['source']['excerpt'])
        self.assertEqual(list(self.v.glob('00-archive/hermes/*.md')), [])
        rerun = self.cli()
        self.assertEqual(json.loads(rerun.stdout)['result'], 'already-done')


INBOX_ENTRY = '## 12:51\nNa desktopie po aktualizacji test padał, bo brakowało zmiennej środowiskowej.\n'


def inbox_payload():
    data = payload()
    data['source'].update(application='inbox', models=[], date='2026-10-13',
                          conversation_id='01-inbox/2026-10/2026-10-13.md#12:51', excerpt=INBOX_ENTRY)
    return data


class InboxSourceTests(unittest.TestCase):
    """application=inbox: one timed entry of the daily inbox file becomes the note's source."""

    # Same sandbox as ApprovedTests, without re-running its hermes tests.
    setUp = ApprovedTests.setUp
    cli = ApprovedTests.cli
    snapshot = ApprovedTests.snapshot

    def write_inbox(self, text='# 2026-10-13\n\n' + INBOX_ENTRY + '\n## 15:00\nInny temat.\n'):
        path = self.v / '01-inbox/2026-10/2026-10-13.md'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def test_inbox_entry_is_published_to_inbox_archive(self):
        self.data = inbox_payload()
        self.write_inbox()
        result = self.cli()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        row = json.loads((self.v / '90-meta/manifest.jsonl').read_text())
        self.assertRegex(row['file'], r'^00-archive/inbox/[0-9a-f]{32}\.md$')
        self.assertEqual((self.v / row['file']).read_text(), INBOX_ENTRY)
        fm = yaml.safe_load((self.v / row['note_file']).read_text().split('---')[1])
        self.assertEqual(fm['source']['application'], 'inbox')
        self.assertEqual(fm['source']['conversation_id'], '01-inbox/2026-10/2026-10-13.md#12:51')
        self.assertEqual(list(self.v.glob('00-archive/hermes/*.md')), [])
        rerun = self.cli()
        self.assertEqual(json.loads(rerun.stdout)['result'], 'already-done')

    def test_inbox_file_absent_on_this_clone_is_allowed(self):
        self.data = inbox_payload()
        result = self.cli('--check')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)['result'], 'validated-not-published')

    def test_sensitive_inbox_extract_goes_to_ignored_subdirectory(self):
        self.data = inbox_payload()
        self.data['note'].update(domains=['zdrowie'], sensitive=True)
        result = self.cli()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        row = json.loads((self.v / '90-meta/manifest.jsonl').read_text())
        self.assertRegex(row['file'], r'^00-archive/inbox/sensitive/[0-9a-f]{32}\.md$')

    def test_invalid_inbox_source_is_rejected_without_writes(self):
        cases = {'bad ref': {'conversation_id': 'session-example'},
                 'no time': {'conversation_id': '01-inbox/2026-10/2026-10-13.md'},
                 'month dir mismatch': {'conversation_id': '01-inbox/2026-09/2026-10-13.md#12:51'},
                 'date mismatch': {'date': '2026-10-14'},
                 'path escape': {'conversation_id': '01-inbox/2026-10/../2026-10-13.md#12:51'},
                 'header mismatch': {'excerpt': '## 09:00\nCoś.\n'},
                 'not verbatim': {'excerpt': '## 12:51\nPrzepisana treść.\n'}}
        self.write_inbox()
        for name, change in cases.items():
            with self.subTest(case=name):
                self.data = inbox_payload()
                self.data['source'].update(change)
                before = self.snapshot()
                result = self.cli()
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertEqual(self.snapshot(), before)

if __name__ == '__main__':
    unittest.main()

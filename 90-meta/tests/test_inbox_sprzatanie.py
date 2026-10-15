"""inbox-sprzatanie.py: usuwa z inboxu tylko wpisy z potwierdzoną kopią i notatką; zapisy w piaskownicy."""
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('inbox_sprzatanie', ROOT / '90-meta/inbox-sprzatanie.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

A = '## 09:15\nPierwszy temat, przerobiony.\n'
B = '## 10:37\nDrugi temat, czeka.\n'


class SprzatanieTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.v = Path(tmp.name)
        (self.v / '90-meta').mkdir()
        shutil.copyfile(ROOT / '90-meta/approved-ingest.py', self.v / '90-meta/approved-ingest.py')
        self.inbox = self.v / '01-inbox/2026-10/2026-10-14.md'
        self.inbox.parent.mkdir(parents=True)
        self.h = mod.content_hash_fn(self.v)
        self.rows = []

    def opublikuj(self, excerpt, note_id='n-0001', archiwum=None):
        name = '00-archive/inbox/' + self.h(excerpt).split(':')[1] + '.md'
        (self.v / name).parent.mkdir(parents=True, exist_ok=True)
        (self.v / name).write_text(excerpt if archiwum is None else archiwum)
        note = f'10-notes/{note_id}-x.md'
        (self.v / note).parent.mkdir(parents=True, exist_ok=True)
        (self.v / note).write_text('notatka\n')
        self.rows.append(dict(file=name, content_hash=self.h(excerpt), status='done', notes=[note_id], note_file=note))
        (self.v / '90-meta/manifest.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in self.rows))

    def test_podglad_niczego_nie_zmienia(self):
        self.inbox.write_text('# 2026-10-14\n\n' + A + '\n' + B)
        self.opublikuj(A)
        before = self.inbox.read_text()
        self.assertEqual(len(mod.sprzataj(self.v)), 1)
        self.assertEqual(self.inbox.read_text(), before)

    def test_usuwa_przerobiony_zostawia_czekajacy(self):
        self.inbox.write_text('# 2026-10-14\n\n' + A + '\n' + B)
        self.opublikuj(A)
        self.assertEqual(mod.sprzataj(self.v, wykonaj=True), ['01-inbox/2026-10/2026-10-14.md#09:15 -> n-0001'])
        self.assertEqual(self.inbox.read_text(), '# 2026-10-14\n\n' + B)

    def test_ostatni_wpis_usuwa_plik_i_pusty_katalog(self):
        self.inbox.write_text('# 2026-10-14\n\n' + A)
        self.opublikuj(A)
        mod.sprzataj(self.v, wykonaj=True)
        self.assertFalse(self.inbox.exists())
        self.assertFalse(self.inbox.parent.exists())

    def test_bez_zgodnej_kopii_lub_notatki_nie_usuwa(self):
        self.inbox.write_text('# 2026-10-14\n\n' + A)
        self.opublikuj(A, archiwum='## 09:15\nInna   treść.\n')
        self.assertEqual(mod.sprzataj(self.v, wykonaj=True), [])
        self.opublikuj(A, note_id='n-0002')
        (self.v / '10-notes/n-0002-x.md').unlink()
        self.assertEqual(mod.sprzataj(self.v, wykonaj=True), [])
        self.assertTrue(self.inbox.exists())

    def test_wyciag_hermesa_nie_liczy_sie_jako_przerobiony_inbox(self):
        self.inbox.write_text('# 2026-10-14\n\n' + A)
        self.opublikuj(A)
        self.rows[0]['file'] = self.rows[0]['file'].replace('/inbox/', '/hermes/')
        (self.v / '90-meta/manifest.jsonl').write_text(json.dumps(self.rows[0]) + '\n')
        self.assertEqual(mod.sprzataj(self.v, wykonaj=True), [])


if __name__ == '__main__':
    unittest.main()

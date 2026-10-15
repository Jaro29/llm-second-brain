"""Testy 90-meta/otwarte-watki.py: które statusy trafiają do 30-state/otwarte-watki.md."""
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

META = pathlib.Path(__file__).resolve().parent.parent


def notatka(nid, status, projects, signal=3, date='2026-10-15'):
    return (f"---\ntitle: 'Tytul {nid}'\nid: {nid}\nstatus: {status}\nkind: troubleshooting\nsignal: {signal}\n"
            f"projects: {projects}\nquestion: 'Pytanie {nid}?'\nsource:\n  date: '{date}'\n---\n\n# Tytul {nid}\n")


class OtwarteWatki(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.v = pathlib.Path(self.tmp.name)
        (self.v / '90-meta').mkdir()
        (self.v / '10-notes').mkdir()
        (self.v / '30-state').mkdir()
        shutil.copy(META / 'otwarte-watki.py', self.v / '90-meta' / 'otwarte-watki.py')

    def tearDown(self):
        self.tmp.cleanup()

    def zapisz(self, nid, *args, **kw):
        (self.v / '10-notes' / f'{nid}-x.md').write_text(notatka(nid, *args, **kw), encoding='utf-8')

    def uruchom(self):
        r = subprocess.run([sys.executable, str(self.v / '90-meta' / 'otwarte-watki.py')],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return (self.v / '30-state' / 'otwarte-watki.md').read_text(encoding='utf-8')

    def test_active_i_unresolved_wchodza_resolved_nie(self):
        self.zapisz('n-0001', 'unresolved', '[second-brain]')
        self.zapisz('n-0002', 'active', '[hermes-agent]')
        self.zapisz('n-0003', 'resolved', '[hermes-agent]')
        self.zapisz('n-0004', 'evergreen', '[hermes-agent]')
        out = self.uruchom()
        self.assertIn('n-0001-x', out)
        self.assertIn('n-0002-x', out)
        self.assertNotIn('n-0003-x', out)
        self.assertNotIn('n-0004-x', out)

    def test_status_widoczny_przy_watku_i_w_naglowku(self):
        self.zapisz('n-0001', 'unresolved', '[second-brain]')
        self.zapisz('n-0002', 'active', '[second-brain]')
        self.zapisz('n-0003', 'active', '[second-brain]')
        out = self.uruchom()
        self.assertIn('3 otwartych wątków', out)
        self.assertIn('2 `active`', out)
        self.assertIn('1 `unresolved`', out)
        linia = next(l for l in out.splitlines() if 'n-0002-x' in l)
        self.assertIn('· active ·', linia)

    def test_active_bez_projektu_ma_ten_sam_prog_sygnalu(self):
        self.zapisz('n-0001', 'active', '[]', signal=2)
        self.zapisz('n-0002', 'active', '[]', signal=3)
        out = self.uruchom()
        self.assertNotIn('n-0001-x', out)
        self.assertIn('n-0002-x', out)


if __name__ == '__main__':
    unittest.main()

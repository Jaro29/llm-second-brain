"""Testy 90-meta/compile.py: kompilacja wiki na małym albo pustym korpusie."""
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

META = pathlib.Path(__file__).resolve().parent.parent


def notatka(nid, entities, domains='[programowanie]'):
    return (f"---\ntitle: 'Tytul {nid}'\nid: {nid}\nkind: troubleshooting\nsignal: 3\nstatus: resolved\n"
            f"domains: {domains}\nentities: {entities}\nsummary: 'Streszczenie {nid}.'\n"
            f"source:\n  date: '2026-10-15'\n---\n\n# Tytul {nid}\n")


class Compile(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.v = pathlib.Path(self.tmp.name)
        for d in ('90-meta', '10-notes', '20-wiki'):
            (self.v / d).mkdir()
        shutil.copy(META / 'compile.py', self.v / '90-meta' / 'compile.py')

    def tearDown(self):
        self.tmp.cleanup()

    def uruchom(self, *args):
        r = subprocess.run([sys.executable, str(self.v / '90-meta' / 'compile.py'), *args],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return (self.v / 'index.md').read_text(encoding='utf-8')

    def test_pusty_korpus_daje_pusty_index(self):
        idx = self.uruchom()
        self.assertIn('0 stron zbudowanych z 0 notatek', idx)
        self.assertIn('**0 notatek (0%)', idx)
        self.assertNotIn('Poza zakresem stron celowo', idx)
        self.assertEqual(list((self.v / '20-wiki').glob('*.md')), [])

    def test_pusty_korpus_usuwa_stare_strony(self):
        (self.v / '20-wiki' / 'stara.md').write_text('# stara\n', encoding='utf-8')
        self.uruchom()
        self.assertEqual(list((self.v / '20-wiki').glob('*.md')), [])

    def test_maly_korpus_buduje_strone(self):
        for i in range(1, 6):
            enc = '[Docker, Tlo]' if i == 1 else '[Tlo]'
            (self.v / '10-notes' / f'n-000{i}-x.md').write_text(notatka(f'n-000{i}', enc), encoding='utf-8')
        idx = self.uruchom('1', '0.5')
        self.assertIn('1 stron zbudowanych z 5 notatek', idx)
        self.assertIn('[[docker|Docker]]', idx)
        self.assertIn('Poza zakresem stron celowo: Tlo (5 notatek)', idx)
        self.assertTrue((self.v / '20-wiki' / 'docker.md').exists())


if __name__ == '__main__':
    unittest.main()

"""Testy 90-meta/walidator.py: brakujący source.file na klonie bez 00-archive/.

Źródło, które git i tak ignoruje (stare eksporty w 00-archive/<zrodlo>/), daje ostrzeżenie.
Brak pliku, który git śledzi albo śledziłby (wyciągi 00-archive/hermes|inbox/<32 hex>.md), jest błędem.
"""
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

META = pathlib.Path(__file__).resolve().parent.parent
ENV = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM='1', LC_ALL='C',
           GIT_CEILING_DIRECTORIES=os.path.realpath(tempfile.gettempdir()))  # bez repo nadrzędnego
HEX = '0123456789abcdef' * 2


def notatka(nid, plik):
    return (f"---\nid: {nid}\ntitle: 'Tytul {nid}'\nsignal: 3\ndomains: [programowanie]\n"
            f"summary: '{'Operacyjne streszczenie notatki testowej, wystarczajaco dlugie dla walidatora. ' * 2}'\n"
            f"source:\n  file: '{plik}'\n---\n\n## Pytanie\n\nx\n\n## Źródło\n\ny\n")


class Walidator(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.v = pathlib.Path(self.tmp.name)
        for d in ('90-meta', '10-notes'):
            (self.v / d).mkdir()
        shutil.copy(META / 'walidator.py', self.v / '90-meta' / 'walidator.py')
        shutil.copy(META.parent / '.gitignore', self.v / '.gitignore')   # prawdziwe reguły vaultu
        (self.v / 'taxonomy.md').write_text('### programowanie\n', encoding='utf-8')
        (self.v / '90-meta' / 'next-id').write_text('100\n', encoding='utf-8')
        self.n = 0

    def tearDown(self):
        self.tmp.cleanup()

    def git_init(self):
        subprocess.run(['git', 'init', '-q'], cwd=self.v, env=ENV, check=True)

    def notatka(self, plik):
        self.n += 1
        nid = f'n-{self.n:04d}'
        (self.v / '10-notes' / f'{nid}-x.md').write_text(notatka(nid, plik), encoding='utf-8')

    def uruchom(self):
        return subprocess.run([sys.executable, str(self.v / '90-meta' / 'walidator.py')],
                              cwd=self.v, env=ENV, capture_output=True, text=True)

    def test_brak_zrodla_poza_gitem_to_ostrzezenie(self):
        self.git_init()
        self.notatka('00-archive/claude/0001_rozmowa---stara.md')
        self.notatka('00-archive/claude/0002_inna.md')
        self.notatka('00-archive/perplexity/x.md')
        self.notatka(f'00-archive/hermes/sensitive/{HEX}.md')
        r = self.uruchom()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn('martwy source.file', r.stdout)
        self.assertIn('UWAGA: 4 notatek', r.stdout)
        self.assertIn('00-archive/claude: 2', r.stdout)
        self.assertIn('00-archive/perplexity: 1', r.stdout)
        self.assertTrue(r.stdout.rstrip().endswith('OK'))

    def test_brak_sledzonego_wyciagu_to_blad(self):
        self.git_init()
        self.notatka(f'00-archive/hermes/{HEX}.md')
        self.notatka(f'00-archive/inbox/{HEX}.md')
        r = self.uruchom()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn(f'martwy source.file -> 00-archive/hermes/{HEX}.md', r.stdout)
        self.assertIn(f'martwy source.file -> 00-archive/inbox/{HEX}.md', r.stdout)
        self.assertNotIn('UWAGA', r.stdout)

    def test_brak_zrodla_poza_archiwum_to_blad(self):
        self.git_init()
        self.notatka('90-meta/nie-ma-mnie.md')
        r = self.uruchom()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn('martwy source.file -> 90-meta/nie-ma-mnie.md', r.stdout)

    def test_istniejace_zrodlo_bez_ostrzezenia(self):
        self.git_init()
        p = self.v / '00-archive' / 'claude' / 'jest.md'
        p.parent.mkdir(parents=True)
        p.write_text('x\n', encoding='utf-8')
        self.notatka('00-archive/claude/jest.md')
        r = self.uruchom()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn('UWAGA', r.stdout)

    def test_bez_gita_brak_zrodla_zostaje_bledem(self):
        # Bez repozytorium nie da się ustalić, co jest poza gitem: ostrożnie, błąd.
        self.notatka('00-archive/claude/x.md')
        r = self.uruchom()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn('martwy source.file -> 00-archive/claude/x.md', r.stdout)


if __name__ == '__main__':
    unittest.main()

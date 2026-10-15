#!/usr/bin/env python3
"""Po zalogowaniu: bezpieczny git pull vaultu i powiadomienie, gdy jest coś do zrobienia.

Uruchamiany raz na sesję przez usługę systemd użytkownika `vault-start.service` (instaluje ją podepnij.py).
Pull tylko --ff-only i tylko gdy jest bezpiecznie: brak niezacommitowanych zmian w śledzonych plikach,
brak niewypchniętych commitów, brak przerwanej transakcji approved-ingest/approved-status.
Niczego nie commituje, nie pushuje i nie publikuje. Powiadomienie (notify-send) tylko gdy jest sprawa
do załatwienia; wszystko trafia też do dziennika: journalctl --user -u vault-start

    python3 vault-start.py [--vault ŚCIEŻKA] [--bez-powiadomien] [--proby N]
"""
import argparse
from pathlib import Path
import re
import shutil
import subprocess
import time

HERE = Path(__file__).resolve().parent
JOURNALS = ('00-archive/hermes/.approved-ingest-transaction.json', '90-meta/.approved-status-transaction.json')
WPIS = re.compile(r'^## ', re.M)


def odm(n, jeden, kilka, wiele):
    if n == 1:
        return f'{n} {jeden}'
    return f'{n} {kilka if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14) else wiele}'


def git(vault, *args):
    return subprocess.run(['git', '-C', str(vault), *args], capture_output=True, text=True)


def fetch(vault, proby, przerwa=10):
    # Po zalogowaniu sieć bywa jeszcze niegotowa: kilka prób zamiast zależności od network-online.
    for i in range(proby):
        if git(vault, 'fetch', '-q', 'origin').returncode == 0:
            return True
        if i < proby - 1:
            time.sleep(przerwa)
    return False


def licz(vault, zakres):
    r = git(vault, 'rev-list', '--count', zakres)
    return int(r.stdout.strip()) if r.returncode == 0 else 0


def wpisy_inboxu(vault):
    return sum(len(WPIS.findall(p.read_text(encoding='utf-8', errors='replace')))
               for p in (vault / '01-inbox').glob('*/*.md'))


def sprawdz(vault, proby):
    """Zwraca (sprawy do powiadomienia, linie dziennika)."""
    sprawy, log = [], []
    if not fetch(vault, proby):
        sprawy.append('brak połączenia z GitHubem, pull pominięty')
    else:
        za, przed = licz(vault, 'HEAD..@{u}'), licz(vault, '@{u}..HEAD')
        brudne = [l[3:] for l in git(vault, 'status', '--porcelain', '--untracked-files=no').stdout.splitlines()]
        journal = [j for j in JOURNALS if (vault / j).exists()]
        if journal:
            sprawy.append('przerwana transakcja approved-* (' + ', '.join(journal) + '), uruchom --recover')
        if brudne:
            sprawy.append(odm(len(brudne), 'niezacommitowana zmiana', 'niezacommitowane zmiany', 'niezacommitowanych zmian') + f' (np. {brudne[0]})')
        if przed:
            sprawy.append(odm(przed, 'commit niewypchnięty', 'commity niewypchnięte', 'commitów niewypchniętych'))
        if za and (journal or brudne or przed):
            sprawy.append('pull pominięty, na GitHubie czeka: ' + odm(za, 'commit', 'commity', 'commitów'))
        elif za:
            r = git(vault, 'pull', '-q', '--ff-only')
            if r.returncode:
                sprawy.append('git pull nie przeszedł: ' + (r.stderr.strip().splitlines() or ['?'])[-1])
            else:
                log.append('pobrano ' + odm(za, 'commit', 'commity', 'commitów') + f', HEAD {git(vault, "rev-parse", "--short", "HEAD").stdout.strip()}')
        else:
            log.append('vault aktualny')
    n = wpisy_inboxu(vault)
    if n:
        sprawy.append('inbox: ' + odm(n, 'wpis czeka', 'wpisy czekają', 'wpisów czeka') + ' na „przerób inbox”')
    return sprawy, log


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--vault', type=Path, default=HERE.parent.parent)
    p.add_argument('--bez-powiadomien', action='store_true', help='tylko wypisz, bez notify-send')
    p.add_argument('--proby', type=int, default=12, help='prób git fetch co 10 s (domyślnie 12)')
    a = p.parse_args()
    sprawy, log = sprawdz(a.vault.resolve(), max(1, a.proby))
    for linia in log + sprawy:
        print(linia)
    if sprawy and not a.bez_powiadomien and shutil.which('notify-send'):
        subprocess.run(['notify-send', '-a', 'Second Brain', '-i', 'dialog-information',
                        'Vault: do zrobienia', '\n'.join(sprawy)])
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

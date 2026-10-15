#!/usr/bin/env python3
"""Usuwa z 01-inbox wpisy (sekcje `## HH:MM`) przerobione przez approved-ingest ze źródłem inbox.

Wpis znika tylko wtedy, gdy manifest ma jego content_hash z wyciągiem w 00-archive/inbox/, wyciąg jest
bajtowo identyczny z sekcją, a notatka istnieje. Wszystko inne zostaje. Plik dzienny bez sekcji jest
usuwany, pusty katalog miesiąca też. Bez --wykonaj tylko wypisuje, co by usunął.

    python3 90-meta/inbox-sprzatanie.py [--vault DIR] [--wykonaj]
"""
import argparse
import importlib.util
import json
from pathlib import Path
import re
import sys

SEKCJA = re.compile(r'^## \d\d:\d\d\n.*?(?=^## \d\d:\d\d\n|\Z)', re.S | re.M)


def content_hash_fn(vault):
    # Ta sama funkcja co przy publikacji; plik ma myślnik w nazwie, więc import przez spec.
    spec = importlib.util.spec_from_file_location('approved_ingest', vault / '90-meta/approved-ingest.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.content_hash


def przerobione(vault):
    rows = [json.loads(line) for line in (vault / '90-meta/manifest.jsonl').read_text().splitlines() if line.strip()]
    return {r['content_hash']: r for r in rows
            if r.get('status') == 'done' and str(r.get('file', '')).startswith('00-archive/inbox/')}


def zachowany(vault, row, excerpt):
    archiwum, notatka = vault / row['file'], vault / row.get('note_file', '')
    return (archiwum.is_file() and archiwum.read_bytes() == excerpt.encode('utf-8')
            and row.get('note_file') and notatka.is_file())


def sprzataj(vault, wykonaj=False):
    content_hash, done = content_hash_fn(vault), przerobione(vault)
    raport = []
    for plik in sorted((vault / '01-inbox').glob('*/*.md')):
        tekst = plik.read_text(encoding='utf-8')
        sekcje = list(SEKCJA.finditer(tekst))
        if not sekcje:
            continue
        usun = []
        for m in sekcje:
            excerpt = m.group(0).rstrip('\n') + '\n'  # tak samo jak przy budowie payloadu
            row = done.get(content_hash(excerpt))
            if row and zachowany(vault, row, excerpt):
                usun.append(m)
                raport.append(f'{plik.relative_to(vault)}#{excerpt[3:8]} -> {row["notes"][0]}')
        if not usun or not wykonaj:
            continue
        zostaje = [m.group(0).rstrip('\n') for m in sekcje if m not in usun]
        if zostaje:
            naglowek = tekst[:sekcje[0].start()].rstrip('\n')
            plik.write_text(naglowek + '\n\n' + '\n\n'.join(zostaje) + '\n', encoding='utf-8')
        else:
            plik.unlink()
            if not any(plik.parent.iterdir()):
                plik.parent.rmdir()
    return raport


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--vault', type=Path, default=Path(__file__).resolve().parents[1])
    p.add_argument('--wykonaj', action='store_true', help='naprawdę usuń (domyślnie tylko podgląd)')
    a = p.parse_args()
    raport = sprzataj(a.vault.resolve(), a.wykonaj)
    tryb = 'usunięto' if a.wykonaj else 'do usunięcia (podgląd, dodaj --wykonaj)'
    print(f'{tryb}: {len(raport)}')
    for r in raport:
        print('  ' + r)
    return 0


if __name__ == '__main__':
    sys.exit(main())

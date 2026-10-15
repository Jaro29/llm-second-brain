#!/usr/bin/env python3
# Eksport pelnych transkryptow sesji Hermesa z ~/.hermes/state.db do 00-archive/hermes-desktop/.
# Odczyt bazy wylacznie read-only. Plik wyjsciowy pelny, nie wybor tematyczny:
# wyciag tematyczny do approved-ingest skleja operator z zakresu wiadomosci eksportu.
# Uzycie:
#   python3 90-meta/eksport-hermes.py --lista            # podglad zakonczonych sesji
#   python3 90-meta/eksport-hermes.py <session_id>       # jedna sesja
#   python3 90-meta/eksport-hermes.py --wszystkie        # wszystkie zakonczone z trescia
import argparse
import json
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

DB = Path.home() / '.hermes' / 'state.db'
KATALOG = '00-archive/hermes-desktop'
STREFA = ZoneInfo('Europe/Warsaw')
SEKCE_JS = re.compile(r'\s*(?:```|~~~)')
KURS = re.compile(r'[^\w-]')

def czytaj_sesje(ses_id):
    conn = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    try:
        ses = conn.execute(
            'SELECT id, source, profile_name, model, started_at, ended_at, message_count, title'
            ' FROM sessions WHERE id = ?', (ses_id,)).fetchone()
        if not ses:
            return None, []
        wiad = conn.execute(
            'SELECT id, role, content, tool_name, tool_calls, timestamp, compacted'
            ' FROM messages WHERE session_id = ? AND active = 1 ORDER BY id', (ses_id,)).fetchall()
        return ses, wiad
    finally:
        conn.close()

def zakonczone():
    conn = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(
            'SELECT id, source, profile_name, model, started_at, ended_at, message_count, title'
            ' FROM sessions WHERE ended_at IS NOT NULL ORDER BY started_at').fetchall()
    finally:
        conn.close()

def czas(ts):
    if ts is None:
        return 'nie dotyczy', 'nie dotyczy', 'nie dotyczy'
    utc = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    war = datetime.fromtimestamp(ts, tz=STREFA).isoformat()
    return utc, war, f'{ts:.7f}'

def blok(etk, jezyk, tekst):
    tekst = tekst.rstrip('\n')
    znacznik = '```'
    while znacznik in tekst:
        znacznik += '`'
    return f'{etk}:\n\n{znacznik}{jezyk}\n{tekst}\n{znacznik}\n'

def slug(tytul):
    tytul = (tytul or 'bez-tytulu').lower()
    tytul = KURS.sub('-', tytul).strip('-')
    return tytul[:60] or 'bez-tytulu'

def eksportuj(ses, wiad):
    st = datetime.fromtimestamp(ses['started_at'], tz=STREFA)
    etu, etw, _ = czas(ses['ended_at'])
    linie = [
        f"# Sesja Hermes: {ses['title'] or 'bez tytulu'}",
        '',
        f"Identyfikator sesji: `{ses['id']}`. Zrodlo: `{ses['source']}`; profil: `{ses['profile_name']}`;"
        f" model sesji: `{ses['model'] or 'nieznany'}` (metadane sesji, nie dowod modelu kazdej wiadomosci).",
        f"Start: {st.isoformat()}; koniec UTC: {etu}; koniec Europe/Warsaw: {etw}. Komunikatow w sesji: {ses['message_count']};"
        f" eksport obejmuje wiadomosci aktywnych z trescia lub wywolaniami narzedzi.",
        'Odczyt SQLite wylacznie read-only z `~/.hermes/state.db`. Pelny eksport, nie wybor tematyczny;'
        ' tresci i wywolania narzedzi sa oryginalami z bazy, nie parafraza.',
        'Znaczniki czasu pochodza z `messages.timestamp`; pola czasu UTC i Europe/Warsaw sa konwersja'
        ' tej samej wartosci Unix. Kolejnosc po `messages.id`.',
        '',
    ]
    licz = 0
    for m in wiad:
        tresc = (m['content'] or '').strip()
        wywolania = (m['tool_calls'] or '').strip()
        if not tresc and not wywolania:
            continue
        licz += 1
        utc, war, unix = czas(m['timestamp'])
        narz = m['tool_name'] or 'nie dotyczy'
        komp = ' [wiadomosc skompresowana]' if m['compacted'] else ''
        linie += [
            f"## Wiadomosc zrodlowa - ID {m['id']}",
            '',
            f"Sesja: `{ses['id']}`; profil: `{ses['profile_name']}`; rola: `{m['role']}`;"
            f" narzedzie: `{narz}`.{komp}",
            f"Czas UTC: `{utc}`; Europe/Warsaw: `{war}`; timestamp Unix: `{unix}`.",
            '',
        ]
        if tresc:
            jezyk = 'json' if m['role'] == 'tool' else 'text'
            linie.append(blok(f"Tresc oryginalna (`content`)", jezyk, tresc))
        if wywolania:
            linie.append(blok('Oryginalne wywolania (`tool_calls`)', 'json', wywolania))
        linie.append('')
    return '\n'.join(linie), licz

def sciezka(ses, katalog):
    dzien = datetime.fromtimestamp(ses['started_at'], tz=STREFA).strftime('%Y-%m-%d')
    return Path(katalog) / f"{ses['id']}_{dzien}_{slug(ses['title'])}.md"

def main():
    p = argparse.ArgumentParser(description='Eksport sesji Hermesa do 00-archive/hermes-desktop/')
    p.add_argument('sesja', nargs='?', help='identyfikator sesji')
    p.add_argument('--lista', action='store_true', help='wypisz zakonczone sesje')
    p.add_argument('--wszystkie', action='store_true', help='eksportuj wszystkie zakonczone z trescia')
    p.add_argument('--katalog', default=KATALOG)
    args = p.parse_args()
    katalog = args.katalog

    if args.lista:
        for s in zakonczone():
            st = datetime.fromtimestamp(s['started_at'], tz=STREFA)
            print(f"{s['id']}\t{st:%Y-%m-%d %H:%M}\t{s['source']}\t{s['message_count']:>4}\t{s['title'] or ''}")
        return 0

    pary = []
    if args.wszystkie:
        pary = [(s, ) for s in zakonczone()]
    elif args.sesja:
        ses, wiad = czytaj_sesje(args.sesja)
        if not ses:
            print(f'brak sesji: {args.sesja}', file=sys.stderr); return 1
        Path(katalog).mkdir(parents=True, exist_ok=True)
        tekst, licz = eksportuj(ses, wiad)
        sc = sciezka(ses, katalog)
        sc.write_text(tekst, encoding='utf-8')
        print(f'{sc} (wiadomosci z trescia: {licz})')
        return 0
    else:
        p.error('podaj identyfikator sesji albo --lista / --wszystkie')

    Path(katalog).mkdir(parents=True, exist_ok=True)
    for (s, ) in pary:
        ses, wiad = czytaj_sesje(s['id'])
        if not ses:
            continue
        if not wiad or all(not (m['content'] or '').strip() and not (m['tool_calls'] or '').strip() for m in wiad):
            print(f'pomijam (brak tresci): {s["id"]}')
            continue
        tekst, licz = eksportuj(ses, wiad)
        sc = sciezka(ses, katalog)
        sc.write_text(tekst, encoding='utf-8')
        print(f'{sc} (wiadomosci z trescia: {licz})')
    return 0

if __name__ == '__main__':
    sys.exit(main())

#!/usr/bin/env python3
"""Buduje 30-state/otwarte-watki.md z notatek o status: unresolved albo active.

  python3 90-meta/otwarte-watki.py [ile_na_grupe]

unresolved = rozmowa urwana bez rozwiazania, active = watek ma ciag dalszy (np. czeka na poprawke upstream).
Grupuje po projekcie, w grupie od najnowszych. Notatki wrazliwe pomija (plik idzie do gita).
Plik jest generowany w calosci przy kazdym uruchomieniu: nie edytuj go recznie,
rozstrzygniete watki zamykaj zmieniajac `status` w samej notatce.
"""
import collections, pathlib, sys, yaml

V = pathlib.Path(__file__).resolve().parent.parent
LIMIT = int(sys.argv[1]) if len(sys.argv) > 1 else 15
STATUSY = ('unresolved', 'active')

notes = []
for p in sorted(V.glob('10-notes/*.md')):          # bez sensitive/, celowo
    if p.name.startswith('_'): continue
    d = yaml.safe_load(p.read_text(encoding='utf-8').split('\n---\n')[0][4:])
    if d.get('status') in STATUSY:
        d['_p'] = p; notes.append(d)
notes.sort(key=lambda d: str(d['source']['date']), reverse=True)

grupy = collections.defaultdict(list)
for d in notes:
    prs = d.get('projects') or []
    if prs:
        for pr in prs: grupy[pr].append(d)
    elif d['signal'] >= 3:
        # bez projektu i o niskim sygnale to zwykle urwany jednorazowy problem, nie watek do domkniecia
        grupy['(bez projektu, sygnal 3+)'].append(d)

ile = collections.Counter(d['status'] for d in notes)
out = ['# Otwarte wątki\n',
       f'_Generowane przez `90-meta/otwarte-watki.py`. {len(notes)} otwartych wątków: '
       f"{ile['unresolved']} `unresolved`, {ile['active']} `active`; "
       f'notatki bez projektu wchodzą tu dopiero od `signal: 3`._',
       '_Nie edytuj ręcznie: wątek zamykasz, zmieniając `status` w notatce przez `90-meta/approved-status.py`._\n',
       'Rozmowy, które urwały się bez rozwiązania (`unresolved`) albo mają ciąg dalszy (`active`). '
       'Najnowsze na górze. Notatki wrażliwe pominięte.\n']
for pr, lista in sorted(grupy.items(), key=lambda x: -len(x[1])):
    out.append(f'## {pr} ({len(lista)})\n')
    for d in lista[:LIMIT]:
        out.append(f"- **[[{d['_p'].stem}|{d['title']}]]** <small>{d['source']['date']} · {d['status']} · "
                   f"{d['kind']} · sig{d['signal']}</small>  \n  {d.get('question', '').strip()}")
    if len(lista) > LIMIT:
        out.append(f'\n_...oraz {len(lista) - LIMIT} starszych, filtr: `status: unresolved|active` + `projects: {pr}`._')
    out.append('')
(V / '30-state' / 'otwarte-watki.md').write_text('\n'.join(out) + '\n', encoding='utf-8')
print(f'{len(notes)} otwartych watkow w {len(grupy)} grupach -> 30-state/otwarte-watki.md')
print(' | '.join(f'{k}: {len(v)}' for k, v in sorted(grupy.items(), key=lambda x: -len(x[1]))[:6]))

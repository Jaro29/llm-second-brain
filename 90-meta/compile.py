#!/usr/bin/env python3
"""Kompilacja warstwy wiki z notatek. Deterministyczna, bez modelu, bez kosztu.
Uruchom z korzenia vaultu:  python3 90-meta/compile.py

Strona powstaje dla encji, ktora wystepuje w co najmniej FLOOR notatkach
i w mniej niz CEIL procentach korpusu. Sufit odsiewa stale srodowiskowe
(np. nazwa systemu, na ktorym pracuje sie na co dzien: to tlo, nie temat).

Strony sa PRZEPISYWANE w calosci przy kazdym uruchomieniu. Recznych zmian
w 20-wiki/ nie wprowadzac, przepadna. Synteza modelem dokladana osobno,
jako sekcja na gorze pliku, poza znacznikiem AUTO.
"""
import yaml, pathlib, collections, re, sys, datetime

V = pathlib.Path(__file__).resolve().parent.parent
FLOOR = int(sys.argv[1]) if len(sys.argv) > 1 else 8
CEIL = float(sys.argv[2]) if len(sys.argv) > 2 else 0.20
AUTO = '<!-- AUTO: ponizej wszystko generowane przez compile.py -->'

def _wczytaj_aliasy():
    """wariant -> forma kanoniczna, z 90-meta/aliasy-encji.txt"""
    a, f = {}, V / '90-meta' / 'aliasy-encji.txt'
    if not f.exists(): return a
    global KANON
    for line in f.read_text(encoding='utf-8').splitlines():
        line = line.split('#')[0].strip()
        if '=' not in line: continue
        kanon, warianty = line.split('=', 1)
        KANON[_baza(kanon)] = kanon.strip()
        for w in warianty.split(','):
            if w.strip(): a[_baza(w)] = _baza(kanon)
    return a

def _baza(e):
    e = e.strip().rsplit('/', 1)[-1]                 # CohereLabs/model -> model
    e = re.sub(r'[\s\-_.]', '', e.lower())
    e = re.sub(r'\d+$', '', e)                       # GNOME 46 -> gnome
    return e or e

def _wczytaj_stopliste():
    f = V / '90-meta' / 'stoplista-encji.txt'
    if not f.exists(): return set()
    return {_baza(l) for l in f.read_text(encoding='utf-8').splitlines()
            if l.strip() and not l.startswith('#')}
STOP = None
ALIASY = None
KANON = {}          # znormalizowany klucz -> nazwa z lewej strony aliasu (wygrywa nad forma najczestsza)
def tytul_dla(e, forms):
    if ALIASY is None: norm('')
    return KANON.get(e) or forms[e].most_common(1)[0][0]
def norm(e):
    global ALIASY
    if ALIASY is None: ALIASY = _wczytaj_aliasy()
    b = _baza(e)
    return ALIASY.get(b, b)
slug = lambda t: (re.sub(r'-+', '-', re.sub(r'[^a-z0-9ąćęłńóśźż]+', '-', t.lower())).strip('-') or 'strona')

def sekcja(txt, nazwa):
    m = re.search(rf'^## {nazwa}\n(.*?)(?=\n## |\Z)', txt, re.S | re.M)
    return m.group(1).strip() if m else ''

# --- wczytanie notatek (sensitive nie bierze udzialu w Compile) ---
notes = []
for p in sorted(V.glob('10-notes/*.md')):
    raw = p.read_text(encoding='utf-8')
    d = yaml.safe_load(raw.split('\n---\n')[0][4:])
    d['_p'], d['_raw'] = p, raw
    notes.append(d)
N = len(notes)
STEM_BY_ID = {str(d.get('id')): d['_p'].stem for d in notes if d.get('id')}

def pelne_wikilinki(text):
    """Rozwija [[n-1234]] do pełnego stemu, jeśli notatka istnieje."""
    return re.sub(r'\[\[(n-[0-9]{4,})\]\]',
                  lambda m: f'[[{STEM_BY_ID.get(m.group(1), m.group(1))}]]', text)

def skroc_bez_psucia_wikilinka(text, limit=420):
    """Skraca tekst poza otwartym wikilinkiem, aby nie generować martwych celów."""
    if len(text) <= limit:
        return text
    cut = text[:limit]
    if cut.rfind('[[') > cut.rfind(']]'):
        cut = cut[:cut.rfind('[[')].rstrip()
    return cut + '...'

# --- kandydaci na strony ---
cnt = collections.Counter(); forms = collections.defaultdict(collections.Counter)
for d in notes:
    for e in set(norm(x) for x in (d.get('entities') or [])): cnt[e] += 1
    for x in (d.get('entities') or []): forms[norm(x)][x.strip()] += 1
STOP = _wczytaj_stopliste()
strony = {e for e, c in cnt.items() if c >= FLOOR and c / N < CEIL and e not in STOP}
tlo = sorted((tytul_dla(e, forms), cnt[e]) for e in cnt if cnt[e] / N >= CEIL)

wiki = V / '20-wiki'
for old in wiki.glob('*.md'): old.unlink()

zbudowane = []
for e in sorted(strony, key=lambda x: (-cnt[x], tytul_dla(x, forms).casefold())):
    tytul = tytul_dla(e, forms)
    grupa = [d for d in notes if e in {norm(x) for x in (d.get('entities') or [])}]
    grupa.sort(key=lambda d: str(d['source']['date']), reverse=True)
    daty = [str(d['source']['date']) for d in grupa]
    dom = collections.Counter(x for d in grupa for x in d['domains'])
    out = [f'# {tytul}\n',
           f'*{len(grupa)} notatek, {min(daty)} do {max(daty)}. '
           f'Domeny: {", ".join(f"{k} ({v})" for k, v in dom.most_common(4))}.*\n',
           ]
    syn = V / '90-meta' / 'synteza' / f'{slug(tytul)}.md'
    if syn.exists():
        out.append(syn.read_text(encoding='utf-8').strip() + '\n')
    out.append(AUTO + '\n')

    # Notatki wyparte (status: superseded) nie trafiaja do pulapek i sa oznaczone na liscie,
    # zeby agent nie bral ich za aktualny stan.
    pul = [(d, sekcja(d['_raw'], 'Pułapki i uwagi')) for d in grupa
           if d['signal'] >= 3 and d.get('status') != 'superseded']
    pul = [(d, s) for d, s in pul if s and not s.lower().startswith('brak')]
    if pul:
        out.append(f'## Pułapki i uwagi ({len(pul)})\n')
        out.append('Dosłownie z notatek o wyższym sygnale. Tego nie ma w dokumentacji.\n')
        for d, s in pul[:12]:
            s = skroc_bez_psucia_wikilinka(pelne_wikilinki(' '.join(s.split())))
            out.append(f'- **[[{d["_p"].stem}|{d["title"]}]]** ({d["source"]["date"]}): {s}')
        if len(pul) > 12: out.append(f'\n*plus {len(pul)-12} dalszych, w notatkach.*')
        out.append('')

    out.append('## Notatki\n')
    for kind, ns in sorted(collections.Counter(d['kind'] for d in grupa).most_common(),
                           key=lambda x: -x[1]):
        out.append(f'\n### {kind} ({ns})\n')
        for d in [x for x in grupa if x['kind'] == kind]:
            # pelne streszczenie tylko dla notatek o wyzszym sygnale; reszta jako link.
            # signal 2 to dwie trzecie korpusu i to one rozdymaly strone do 44 kB.
            if d.get('status') == 'superseded':
                nowa = d.get('superseded_by')
                out.append(f'- ~~[[{d["_p"].stem}|{d["title"]}]]~~ <small>{d["source"]["date"]} · '
                           f'zastąpione przez [[{STEM_BY_ID.get(nowa, nowa)}|{nowa}]]</small>')
            elif d['signal'] >= 3:
                out.append(f'- **[[{d["_p"].stem}|{d["title"]}]]** <small>{d["source"]["date"]} · sig{d["signal"]}</small>  ')
                out.append(f'  {" ".join(str(d["summary"]).split())}')
            else:
                out.append(f'- [[{d["_p"].stem}|{d["title"]}]] <small>{d["source"]["date"]}</small>')

    kod = [d for d in grupa if sekcja(d['_raw'], 'Kod')]
    if kod:
        out.append(f'\n## Kod\n')
        out.append(f'{len(kod)} notatek zawiera kod. Nie kopiuje go tutaj: strona ma prowadzic do notatki, nie ja zastepowac.\n')
        out.append(', '.join(f'[[{d["_p"].stem}|{d["title"]}]]' for d in kod))

    (wiki / f'{slug(tytul)}.md').write_text('\n'.join(out) + '\n', encoding='utf-8')
    zbudowane.append((tytul, len(grupa), slug(tytul)))

# --- index ---
pokryte = {d['_p'].stem for e in strony for d in notes
           if e in {norm(x) for x in (d.get('entities') or [])}}
sierot = N - len(pokryte)
pct_sierot = 100 * sierot / N if N else 0     # pusty korpus (np. wizytowka przed pierwsza notatka)
dom_all = collections.Counter(x for d in notes for x in d['domains'])
idx = ['# index.md\n',
       f'Katalog warstwy wiki. {len(zbudowane)} stron zbudowanych z {N} notatek, '
       f'przez `compile.py` (prog {FLOOR} notatek, sufit {CEIL:.0%}).\n',
       '> **Ważne dla agenta:** ten indeks pokrywa wyłącznie tematy, które wystąpiły',
       f'> wystarczająco często, żeby dało się z nich coś złożyć. **{sierot} notatek ({pct_sierot:.0f}%)',
       '> nie ma swojej strony**, bo ich temat pojawił się raz lub dwa. Brak strony nie znaczy',
       '> brak wiedzy: te notatki leżą w `10-notes/` i znajduje się je wyszukiwaniem',
       '> pełnotekstowym oraz filtrem po `domains`, `kind` i `projects` (wzorce w `router.md`).\n']
if tlo:
    idx.append(f'Poza zakresem stron celowo: {", ".join(f"{t} ({c} notatek)" for t, c in tlo)} '
               '- to stała twojego środowiska, opisana w `30-state/identity-hardware.md`, nie temat.\n')
idx.append('## Strony\n')
for t, c, s in zbudowane: idx.append(f'- [[{s}|{t}]] <small>{c} notatek</small>')
idx.append('\n## Notatki wg domeny\n')
idx.append('Do zejścia poziom niżej, gdy strona nie odpowiada.\n')
for k, v in dom_all.most_common():
    idx.append(f'- `domains: {k}` <small>{v} notatek</small>')
(V / 'index.md').write_text('\n'.join(idx) + '\n', encoding='utf-8')

print(f'odsiane stoplista: {sum(1 for e in cnt if e in STOP and cnt[e] >= FLOOR)}')
print(f'{len(zbudowane)} stron z {N} notatek | bez strony: {sierot} ({pct_sierot:.0f}%)')
print(f'odsiane sufitem: {", ".join(t for t, _ in tlo) or "brak"}')
print('najwieksze:', ', '.join(f'{t} ({c})' for t, c, _ in zbudowane[:6]))

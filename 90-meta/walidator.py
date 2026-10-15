#!/usr/bin/env python3
"""Sprawdza reguly, ktorych schemat JSON nie wyrazi. Uruchom z korzenia vaulta:
     python3 90-meta/walidator.py
Zwraca kod 1, gdy cokolwiek nie przechodzi. Brak source.file, ktory git ignoruje (stare eksporty
w 00-archive/, ktorych klon nie ma), to tylko ostrzezenie: hook pre-commit dziala na kazdym klonie."""
import yaml, re, sys, pathlib, subprocess, collections
V = pathlib.Path(__file__).resolve().parent.parent
tax = (V / 'taxonomy.md').read_text(encoding='utf-8')
DOM = set(re.findall(r'^### ([a-z0-9-]+)$', tax, re.M))
# Kandydaci na haslo. Sama regula ksztaltu daje mnostwo falszywych trafien
# (prompty powloki user@host, adresy git@github, nazwy z kodu JCTree$JCImport),
# dlatego kandydat musi jeszcze przejsc test entropii w haslo().
KAND = re.compile(r'(?<![`/\w])[A-Za-z][A-Za-z0-9]{2,}[@$#!%][A-Za-z0-9@$#!%]{4,}(?![\w`])')
def haslo(s):
    return (sum(c.isdigit() for c in s) >= 2 and any(c in '@$#!%' for c in s)
            and any(c.islower() for c in s) and any(c.isupper() for c in s))
def ma_poswiadczenie(txt):
    return any(haslo(m) for m in KAND.findall(txt))
err = []
brak = []   # (notatka, source.file) bez pliku; podzial na blad/ostrzezenie po petli

def poza_gitem(sciezki):
    """Ktore sciezki git ignoruje, czyli leza poza gitem z zalozenia (stare eksporty w 00-archive/).
    Na klonie bez 00-archive/ ich brak jest normalny. Bez gita: zadna (ostroznie, zostaja bledem)."""
    if not sciezki: return set()
    try:
        r = subprocess.run(['git', 'check-ignore', '-z', '--stdin'], cwd=V, capture_output=True,
                           text=True, input=''.join(s + '\0' for s in sciezki))
    except Exception: return set()
    return set(filter(None, r.stdout.split('\0'))) if r.returncode in (0, 1) else set()

def fm(p):
    t = p.read_text(encoding='utf-8')
    if not t.startswith('---\n'): return None, t
    raw = t.split('\n---\n', 1)[0][4:]
    try: return yaml.safe_load(raw) or {}, t
    except Exception as e: return {'_bad': str(e)}, t

notes = sorted(V.glob('10-notes/**/*.md'))
for p in notes:
    r = str(p.relative_to(V)); d, t = fm(p)
    if d is None: err.append(f'{r}: brak frontmattera'); continue
    if '_bad' in d: err.append(f'{r}: nieparsowalny frontmatter ({d["_bad"]})'); continue
    if not p.name.startswith(d.get('id', '') + '-'): err.append(f'{r}: nazwa pliku nie zaczyna sie od id {d.get("id")}')
    if d.get('signal', 0) < 2: err.append(f'{r}: signal={d.get("signal")} nie powinien miec notatki')
    if d.get('sensitive') and p.parent.name != 'sensitive': err.append(f'{r}: sensitive poza 10-notes/sensitive/')
    if not d.get('sensitive') and p.parent.name == 'sensitive': err.append(f'{r}: nie-sensitive w sensitive/')
    if set(d.get('domains') or []) & {'zdrowie','finanse-podatki'} and not d.get('sensitive'):
        err.append(f'{r}: domena wrazliwa ({set(d["domains"]) & {"zdrowie","finanse-podatki"}}) bez sensitive')
    if d.get('status') == 'superseded' and not d.get('superseded_by'): err.append(f'{r}: superseded bez superseded_by')
    for dom in d.get('domains', []):
        if dom not in DOM: err.append(f'{r}: domena spoza taksonomii: {dom}')
    if not d.get('domains'): err.append(f'{r}: brak domen')
    if len(d.get('domains') or []) != len(set(d.get('domains') or [])): err.append(f'{r}: zdublowana domena')
    f = d.get('source', {}).get('file', '')
    if f and not (V / f).exists(): brak.append((r, f))
    if len(d.get('summary', '')) < 80: err.append(f'{r}: summary za krotkie')
    if re.match(r'^(Rozmowa|Notatka|Użytkownik|Autor)\s+(dotyczy|opisuje|poprosił|szukał|zwrócił|pytał|chciał|zapytał)', d.get('summary', '')):
        err.append(f'{r}: summary narracyjne ("Uzytkownik poprosil...") zamiast operacyjnego')
    if not d.get('sensitive') and ma_poswiadczenie(t):
        err.append(f'{r}: wyglada na poswiadczenie w tresci, a sensitive=false')
    for h in ('## Pytanie', '## Źródło'):
        if h not in t: err.append(f'{r}: brak sekcji {h}')

# Brakujace zrodlo: ignorowane przez git (stary eksport, ktorego klon bez 00-archive/ nie ma) -> ostrzezenie;
# kazde inne (np. sledzony wyciag 00-archive/hermes|inbox/<32 hex>.md) -> blad.
ign = poza_gitem(sorted({f for _, f in brak}))
uwagi = collections.Counter()
for r, f in brak:
    if f in ign: uwagi['/'.join(f.split('/')[:2])] += 1
    else: err.append(f'{r}: martwy source.file -> {f}')

ids = [fm(p)[0].get('id') for p in notes if fm(p)[0] and '_bad' not in fm(p)[0]]
dup = {i for i in ids if ids.count(i) > 1}
if dup: err.append(f'zdublowane id: {sorted(dup)}')
for p in notes:
    d = fm(p)[0]
    sb = d and '_bad' not in d and d.get('superseded_by')
    if sb and sb not in ids: err.append(f'{p.relative_to(V)}: superseded_by -> {sb}, takiej notatki nie ma')
    if sb and sb == d.get('id'): err.append(f'{p.relative_to(V)}: superseded_by wskazuje na siebie')
nxt = int((V / '90-meta/next-id').read_text().strip())
mx = max((int(i[2:]) for i in ids if i), default=0)
if nxt <= mx: err.append(f'next-id={nxt} nie jest wiekszy od najwyzszego id n-{mx:04d}')

try:
    sled = subprocess.run(['git','ls-files','.env'], cwd=V, capture_output=True, text=True).stdout.strip()
    if sled: err.append('KRYTYCZNE: .env jest sledzony przez git. Uruchom: git rm --cached .env')
except Exception: pass

print(f'sprawdzono {len(notes)} notatek')
if uwagi:
    print(f'  UWAGA: {sum(uwagi.values())} notatek wskazuje source.file poza gitem, ktorego brak w tym klonie '
          f'({", ".join(f"{k}: {v}" for k, v in sorted(uwagi.items()))}); normalne na klonie bez 00-archive/')
for e in err: print('  BLAD:', e)
print('OK' if not err else f'{len(err)} bledow')
sys.exit(1 if err else 0)

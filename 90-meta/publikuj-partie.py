#!/usr/bin/env python3
"""Publikacja zatwierdzonej partii w jednym przebiegu, bez możliwości zostawienia jej niewypchniętej.

Payloady approved-ingest (klucz `source`) i approved-status (klucz `status`) można mieszać w jednej partii.
Kolejność: git fetch -> --check wszystkich (błąd = nic nie zapisane) -> publikacja po kolei -> walidator ->
compile.py -> otwarte-watki.py -> commit z jawną listą plików -> push -> weryfikacja na origin/main ->
inbox-sprzatanie.py (gdy w partii były wpisy z inboxu). Publikować tylko partię zatwierdzoną przez operatora.

    python3 90-meta/publikuj-partie.py [--check] [--wznow] [-m OPIS] payload.json [payload.json ...]

--check   tylko fetch i walidacja wszystkich payloadów; niczego nie zapisuje.
--wznow   dokończenie przerwanej partii: niezacommitowane zmiany w ścieżkach partii są dozwolone
          (już opublikowane payloady dają already-done, kolejne idą z --continue-batch).

Kody wyjścia: 0 gotowe; 1 odmowa przed zapisem; 2 przerwane po częściowej publikacji (nic nie zacommitowane,
dokończ z --wznow); 3 commit lokalny, ale push albo weryfikacja na origin/main się nie powiodły.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
# Ścieżki, które partia zmienia: pisane przez approved-ingest/approved-status plus pliki generowane.
GENERATED = ('20-wiki', 'index.md', '30-state/otwarte-watki.md')
BATCH_PATHS = ('10-notes', '00-archive/hermes', '00-archive/inbox', '90-meta/manifest.jsonl',
               '90-meta/next-id', 'log.md') + GENERATED


class Stop(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def git(vault, *args, check=True, env=None):
    r = subprocess.run(['git', '-C', str(vault), '-c', 'core.quotePath=false', *args],
                       capture_output=True, text=True, env=env)
    if check and r.returncode:
        raise Stop(1, f'git {args[0]} nie powiódł się: {r.stderr.strip() or r.stdout.strip()}')
    return r


def kind_of(data):
    if 'source' in data and 'note' in data:
        return 'ingest'
    if 'status' in data and 'note' in data:
        return 'status'
    raise Stop(1, 'nieznany rodzaj payloadu (ani approved-ingest, ani approved-status)')


def run_tool(vault, kind, path, *flags):
    script = vault / '90-meta' / ('approved-ingest.py' if kind == 'ingest' else 'approved-status.py')
    r = subprocess.run([sys.executable, str(script), '--vault', str(vault), *flags, str(path)],
                       capture_output=True, text=True)
    if r.returncode:
        return None, (r.stderr.strip() or r.stdout.strip())
    return json.loads(r.stdout), None


def python_step(vault, name, *args):
    r = subprocess.run([sys.executable, str(vault / '90-meta' / name), *args], capture_output=True, text=True,
                       cwd=vault)
    return r.returncode, (r.stdout + r.stderr).strip()


def label(kind, res):
    if kind == 'ingest':
        return res['notes'][0]
    return f"{res['note']} {res['from']}->{res['to']}"


def publikuj(vault, paths, check=False, wznow=False, opis=None):
    items = []
    for p in paths:
        data = json.loads(Path(p).read_text(encoding='utf-8'))
        items.append({'path': Path(p).resolve(), 'kind': kind_of(data), 'data': data})

    # 1. Świeży stan z GitHuba: strażnik approved-* wymaga fetcha i sprawdza, czy nie jesteśmy za origin.
    git(vault, 'fetch', '-q', 'origin')
    dirty = git(vault, 'status', '--porcelain=v1', '--untracked-files=all', '--', *BATCH_PATHS).stdout.splitlines()
    if dirty and not wznow:
        raise Stop(1, f'{len(dirty)} niezacommitowanych zmian w ścieżkach partii (np. {dirty[0][3:]}); '
                      'zacommituj je albo dokończ przerwaną partię z --wznow')
    batch_flag = ['--continue-batch'] if dirty else []

    # 2. Walidacja całej partii, zanim cokolwiek trafi do vaulta.
    for it in items:
        res, err = run_tool(vault, it['kind'], it['path'], '--check', *batch_flag)
        if err:
            raise Stop(1, f'{it["path"].name}: --check odrzucił payload, partia niezapisana: {err}')
        it['check'] = res
    if check:
        return {'result': 'validated-not-published',
                'items': [{'payload': it['path'].name, 'kind': it['kind'], 'check': it['check']['result']}
                          for it in items]}

    # 3. Publikacja po kolei; od drugiego payloadu zmiany pierwszych są w drzewie, stąd --continue-batch.
    done = []
    for i, it in enumerate(items):
        res, err = run_tool(vault, it['kind'], it['path'], *(batch_flag if i == 0 else ['--continue-batch']))
        if err:
            raise Stop(2, f'{it["path"].name}: publikacja przerwana: {err}. Opublikowane wcześniej: '
                          f'{[label(d["kind"], d["res"]) for d in done] or "nic"}; nic nie zostało '
                          'zacommitowane. Napraw przyczynę i uruchom tę samą partię z --wznow.')
        it['res'] = res
        done.append({'kind': it['kind'], 'res': res})

    # 4. Walidacja vaulta i pliki generowane.
    for name in ('walidator.py', 'compile.py', 'otwarte-watki.py'):
        code, out = python_step(vault, name)
        if code:
            raise Stop(2, f'{name} zgłosił błąd po publikacji (nic nie zacommitowane, dokończ z --wznow): {out}')

    # 5. Commit z jawną listą plików; pliki sensitive są ignorowane przez gita i zostają lokalnie.
    files = {'90-meta/manifest.jsonl', 'log.md'}
    for it in items:
        files.add(it['res']['note_file'])
        if it['kind'] == 'ingest':
            files.update({it['res']['file'], '90-meta/next-id'})
    files = sorted(f for f in files if (vault / f).exists()
                   and git(vault, 'check-ignore', '-q', f, check=False).returncode != 0)
    git(vault, 'add', '--', *files)
    git(vault, 'add', '-A', '--', *[g for g in GENERATED if (vault / g).exists()])
    staged = git(vault, 'diff', '--cached', '--name-only').stdout.split()
    commit = None
    if staged:
        ids = ', '.join(label(it['kind'], it['res']) for it in items)
        msg = f'publikuj-partie: {opis + "; " if opis else ""}{ids}'
        # Hook pre-commit woła `python3` (walidator): ten sam interpreter co skrypt, bo ma PyYAML.
        env = dict(os.environ, PATH=str(Path(sys.executable).parent) + os.pathsep + os.environ.get('PATH', ''))
        r = git(vault, 'commit', '-q', '-m', msg, check=False, env=env)
        if r.returncode:
            raise Stop(2, f'commit nie powiódł się (zmiany są zestagowane, nic nie wypchnięte): '
                          f'{r.stderr.strip() or r.stdout.strip()}')
        commit = git(vault, 'rev-parse', '--short', 'HEAD').stdout.strip()

    # 6. Push i weryfikacja na origin/main: sam kod wyjścia pusha nie dowodzi publikacji.
    if commit:
        r = git(vault, 'push', '-q', 'origin', 'HEAD', check=False)
        if r.returncode:
            raise Stop(3, f'commit {commit} jest lokalnie, ale push odrzucony: {r.stderr.strip()}. '
                          'Zrób git fetch i git pull --rebase (konflikt w plikach generowanych rozwiąż '
                          'ponownym compile.py/otwarte-watki.py), walidator, potem git push.')
        git(vault, 'fetch', '-q', 'origin')
        if git(vault, 'rev-parse', 'HEAD').stdout != git(vault, 'rev-parse', '@{u}').stdout:
            raise Stop(3, f'po pushu origin/main nie wskazuje na commit {commit}; sprawdź ręcznie')
    for it in items:
        name = it['res']['note_file']
        if '/sensitive/' in name:
            continue
        blob = subprocess.run(['git', '-C', str(vault), 'show', f'origin/main:{name}'], capture_output=True)
        if blob.returncode or blob.stdout != (vault / name).read_bytes():
            raise Stop(3, f'weryfikacja na origin/main nie przeszła dla {name}')

    # 7. Sprzątanie inboxu, gdy partia zawierała jego wpisy.
    sprzatanie = None
    if any(it['kind'] == 'ingest' and it['data']['source'].get('application') == 'inbox' for it in items):
        code, sprzatanie = python_step(vault, 'inbox-sprzatanie.py', '--vault', str(vault), '--wykonaj')
        if code:
            sprzatanie = 'BŁĄD: ' + sprzatanie
    return {'result': 'published', 'commit': commit,
            'items': [{'payload': it['path'].name, 'kind': it['kind'], 'result': it['res']['result'],
                       'id': label(it['kind'], it['res'])} for it in items],
            'inbox': sprzatanie}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--vault', type=Path, default=HERE.parent)
    p.add_argument('--check', action='store_true', help='tylko walidacja, bez zapisu')
    p.add_argument('--wznow', action='store_true', help='dokończ przerwaną partię')
    p.add_argument('-m', dest='opis', help='krótki opis partii do wiadomości commita')
    p.add_argument('payloads', nargs='+')
    a = p.parse_args()
    try:
        out = publikuj(a.vault.resolve(), a.payloads, a.check, a.wznow, a.opis)
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 0
    except Stop as e:
        print(f'ERROR: {e}', file=sys.stderr)
        return e.code


if __name__ == '__main__':
    sys.exit(main())

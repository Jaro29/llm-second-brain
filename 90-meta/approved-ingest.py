#!/usr/bin/env python3
"""Offline, deterministic publication of a human-approved note. See approved-ingest.md."""
import argparse
import base64
from contextlib import contextmanager
import fcntl
import os
import datetime
import hashlib
import json
from pathlib import Path
import re
import sys
import shutil
import subprocess
import tempfile

import yaml
import jsonschema

# hermes: excerpt of a Hermes conversation; inbox: one timed entry of the daily 01-inbox capture.
APPLICATIONS = ('hermes', 'inbox')
INBOX_REF = re.compile(r'01-inbox/(\d{4}-\d{2})/(\d{4}-\d{2}-\d{2})\.md#(\d{2}:\d{2})')


def validate_inbox_source(vault, source):
    # conversation_id is the entry's address: 01-inbox/RRRR-MM/RRRR-MM-DD.md#HH:MM.
    m = INBOX_REF.fullmatch(source['conversation_id'])
    if not m or m[2][:7] != m[1]:
        raise ValueError('inbox source: conversation_id must be 01-inbox/RRRR-MM/RRRR-MM-DD.md#HH:MM')
    if m[2] != source['date']:
        raise ValueError('inbox source: source.date must equal the inbox file date')
    if not source['excerpt'].startswith(f'## {m[3]}\n'):
        raise ValueError('inbox source: excerpt must be the verbatim entry starting with its ## HH:MM header')
    inbox_file = safe_path(vault, source['conversation_id'].split('#')[0])
    # The inbox may be absent on another clone; when present, the excerpt must be copied verbatim.
    if inbox_file.is_file() and source['excerpt'].strip() not in inbox_file.read_text(encoding='utf-8'):
        raise ValueError('inbox source: excerpt is not a verbatim part of the inbox file')

def validate_payload(vault, data):
    # Conservative guard, not a substitute for a human privacy review.
    raw = json.dumps(data, ensure_ascii=False)
    if re.search(r'(sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|'
                 r'AKIA[0-9A-Z]{16}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY|'
                 r'(?i:bearer)\s+[A-Za-z0-9._-]{20,})', raw):
        raise ValueError('possible credential: publication refused; review privately')
    if set(data) != {'approval', 'source', 'note'} or data['approval'] != 'approved':
        raise ValueError('explicit approval required; expected approval/source/note')
    source = data['source']
    if set(source) != {'application', 'models', 'conversation_id', 'date', 'lang', 'excerpt'}:
        raise ValueError('invalid source fields')
    if source['application'] not in APPLICATIONS:
        raise ValueError('source.application must be hermes or inbox (not a model)')
    for key in ('conversation_id', 'date', 'lang', 'excerpt'):
        if not isinstance(source[key], str) or not source[key].strip():
            raise ValueError('invalid source.' + key)
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', source['date']):
        raise ValueError('source.date must be YYYY-MM-DD')
    datetime.date.fromisoformat(source['date'])
    if source['application'] == 'inbox':
        validate_inbox_source(vault, source)
    if not isinstance(source['models'], list) or any(not isinstance(m, str) or not m.strip() for m in source['models']):
        raise ValueError('source.models must be a list of model identifiers; [] if unknown')
    schema = json.loads((vault / '90-meta/schema-notatki.json').read_text())
    # Taxonomy, not a possibly stale generated schema, owns the closed vocabularies.
    tax = (vault / 'taxonomy.md').read_text()
    section = lambda h: tax.split('## ' + h)[1].split('\n## ')[0]
    for key, heading, pattern in [('domains', 'Oś 1', r'^### ([a-z0-9-]+)$'),
                                  ('kind', 'Oś 2', r'^\| `([a-z-]+)` \|'),
                                  ('projects', 'Oś 3', r'^\| `([a-z-]+)` \|'),
                                  ('status', 'Oś 4', r'^\| `([a-z]+)` \|')]:
        values = re.findall(pattern, section(heading), re.M)
        if not values:
            raise ValueError('cannot parse taxonomy ' + key)
        target = schema['properties'][key]
        if key in ('domains', 'projects'):
            target = target['items']
        target['enum'] = values
    # Extensions belong to the offline approval contract, not the model schema.
    schema['properties']['confidence']['type'] = ['number', 'null']
    schema['properties']['related'] = {'type': 'array', 'uniqueItems': True,
        'items': {'type': 'string', 'pattern': r'^n-[0-9]{4,}$'}}
    schema['properties']['zrodlo'] = {'type': 'string'}
    try:
        jsonschema.validate(data['note'], schema)
    except jsonschema.ValidationError:
        raise ValueError('invalid note schema; inspect payload privately') from None
    d = data['note']
    if any(isinstance(value, str) and re.search(r'^\s*#{1,6}\s+Sygnały o mnie\b', value, re.M | re.I)
           for value in d.values()):
        raise ValueError('retired identity section is not allowed in new notes')
    if d['signal'] < 2:
        raise ValueError('approved-note requires signal >= 2')
    if set(d['domains']) & {'zdrowie', 'finanse-podatki'} and not d['sensitive']:
        raise ValueError('sensitive domain requires explicit sensitive=true approval')

VERSION = 'approved-1.0'
# Deliberately identical to legacy ingest.py, including its truncated digest.
TURN = re.compile(r'^(## (Użytkownik|Ty)\s*$|\*\*(Ty|Użytkownik):\*\*)', re.M)
ROLE = re.compile(r'^\s*(#\s*Rola|Jesteś (ekspertem|doświadczonym|wybitnym)|Przyjmij rolę|ROLA:)', re.I)


def content_hash(txt):
    m = TURN.search(txt)
    b = txt[m.start():] if m else txt
    parts = TURN.split(b)
    if len(parts) > 1 and ROLE.match(parts[-1][:200] if parts[-1] else ''):
        b = b[b.find('\n', 200) + 1:]
    return 'sha256:' + hashlib.sha256(re.sub(r'\s+', ' ', b).encode()).hexdigest()[:32]


def approval_hash(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':')).encode()).hexdigest()


def prior_result(vault, data):
    h = content_hash(data['source']['excerpt'])
    rows = [json.loads(line) for line in (vault / '90-meta/manifest.jsonl').read_text().splitlines() if line.strip()]
    matches = [row for row in rows if row.get('content_hash') == h]
    if not matches:
        return None
    if len(matches) != 1 or matches[0].get('approval_hash') != approval_hash(data):
        raise ValueError('content_hash conflict: already recorded with different or legacy approval')
    row = matches[0]
    source = safe_path(vault, row['file'])
    if not source.is_file():
        raise ValueError('unavailable-source: ' + row['file'])
    if source.read_bytes() != data['source']['excerpt'].encode('utf-8'):
        raise ValueError('source drift: preserved excerpt differs')
    note = safe_path(vault, row['note_file'])
    # A later approved status change (approved-status.py) legitimately rewrites the note: trust its newest row.
    status_rows = [r for r in rows if r.get('kind') == 'status' and r.get('note_file') == row['note_file']]
    expected = status_rows[-1]['note_sha256'] if status_rows else row['note_sha256']
    if not note.is_file() or hashlib.sha256(note.read_bytes()).hexdigest() != expected:
        raise ValueError('note drift: missing or edited; no overwrite permitted')
    if row['status'] != 'done' or row['notes'] != [yaml.safe_load(note.read_text().split('---')[1])['id']]:
        raise ValueError('manifest/note inconsistency')
    next_id(vault)
    return dict(row, result='already-done')


def next_id(vault):
    raw = (vault / '90-meta/next-id').read_text().strip()
    if not re.fullmatch(r'[1-9][0-9]*', raw):
        raise ValueError('invalid next-id; never reconstruct from tracked notes')
    nid = int(raw)
    ids = [note_id for line in (vault / '90-meta/manifest.jsonl').read_text().splitlines()
           if line.strip() for note_id in json.loads(line).get('notes', [])]
    for path in vault.glob('10-notes/**/*.md'):
        match = re.match(r'(n-[0-9]+)-', path.name)
        if match:
            ids.append(match[1])
    for note_id in ids:
        if not re.fullmatch(r'n-[0-9]{4,}', note_id):
            raise ValueError('malformed reserved id in manifest/notes')
        if int(note_id[2:]) >= nid:
            raise ValueError('next-id is stale: reserved/existing id ' + note_id)
    return nid


def prepare(vault, data):
    d, source = data['note'], data['source']
    nid = next_id(vault)
    note_id = f'n-{nid:04d}'
    h = content_hash(source['excerpt'])
    # Top-level <application>/*.md extracts are tracked by git; sensitive ones go to an ignored subdirectory.
    archive = (f'00-archive/{source["application"]}/' + ('sensitive/' if d['sensitive'] else '')
               + h.split(':')[1] + '.md')
    src = {k: source[k] for k in ('application', 'models', 'conversation_id', 'date', 'lang')}
    src.update(file=archive, segment=d['segment_of'])
    meta = {k: d[k] for k in ('title', 'summary', 'domains', 'kind', 'projects', 'status',
            'signal', 'sensitive', 'entities', 'question', 'outcome', 'has_code', 'code_langs', 'confidence')}
    meta.update(id=note_id, source=src, related=d.get('related', []), superseded_by=d['superseded_by'] or None,
                wiki=[], ingest_version=VERSION, ingest_model='none:human-approved',
                content_hash=h, human_reviewed=True, human_notes='', human_tags=[])
    text = '---\n' + yaml.safe_dump(meta, allow_unicode=True, sort_keys=False,
                                    default_flow_style=None, width=100) + '---\n'
    text += f'\n# {d["title"]}\n'
    for key, heading in [('kontekst', 'Kontekst'), ('question', 'Pytanie'),
                         ('rozwiazanie', 'Rozwiązanie'), ('kod', 'Kod'),
                         ('pulapki', 'Pułapki i uwagi'), ('decyzje', 'Decyzje')]:
        text += f'\n## {heading}\n{d[key]}\n'
    text += f'\n## Źródło\n`{archive}`, zakres źródła: {d["turns"]}.\n'
    if d.get('zrodlo'):
        text += '\n' + d['zrodlo'] + '\n'
    slug = '-'.join(re.sub(r'[^a-z0-9ąćęłńóśźż ]', '', d['title'].lower()).split())[:50].strip('-') or 'notatka'
    note = f'10-notes/{"sensitive/" if d["sensitive"] else ""}{note_id}-{slug}.md'
    row = dict(file=archive, content_hash=h, approval_hash=approval_hash(data), status='done', ingest_version=VERSION,
               segments=1, notes=[note_id], note_file=note,
               note_sha256=hashlib.sha256(text.encode('utf-8')).hexdigest(),
               signal=d['signal'], errors=[],
               processed_at=datetime.datetime.now(datetime.UTC).isoformat(timespec='seconds'))
    manifest = (vault / '90-meta/manifest.jsonl').read_bytes().decode('utf-8')
    if manifest and not manifest.endswith('\n'):
        manifest += '\n'
    log_path = safe_path(vault, 'log.md')
    log = log_path.read_bytes().decode('utf-8') if log_path.exists() else ''
    if log and not log.endswith('\n'):
        log += '\n'
    log += (f'\n## [{str(row["processed_at"])[:10]}] approved-ingest | {row["processed_at"]} '
            f'{VERSION}: published {note_id}; offline approved Import/Ingest.\n')
    return {archive: source['excerpt'], note: text, 'log.md': log,
            '90-meta/manifest.jsonl': manifest + json.dumps(row, ensure_ascii=False) + '\n',
            '90-meta/next-id': f'{nid + 1}\n'}, row


GUARDED = ('90-meta/next-id', '90-meta/manifest.jsonl', 'log.md', '10-notes', '00-archive/hermes', '00-archive/inbox')
FETCH_MAX_AGE = 3600  # seconds; the guard is only as fresh as the last fetch
UPSTREAM = 'origin/main'
ALLOW_NO_GIT = 'APPROVED_INGEST_ALLOW_NO_GIT'  # test sandboxes only
# Inherited repo-redirecting variables (e.g. inside a git hook) would make -C check another repository.
REDIRECT = ('GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE', 'GIT_COMMON_DIR', 'GIT_OBJECT_DIRECTORY',
            'GIT_ALTERNATE_OBJECT_DIRECTORIES', 'GIT_NAMESPACE',
            'GIT_CONFIG_PARAMETERS', 'GIT_CONFIG_COUNT')  # the last two carry `git -c` from a parent git


def git_run(vault, *args):
    env = {k: v for k, v in os.environ.items() if k not in REDIRECT}
    # Ceiling: a broken vault/.git must fail, not silently fall back to a repository above the vault.
    env.update(GIT_TERMINAL_PROMPT='0', GIT_OPTIONAL_LOCKS='0', LC_ALL='C', GIT_CEILING_DIRECTORIES=str(vault.parent))
    try:
        return subprocess.run(['git', '-C', str(vault), *args], capture_output=True, text=True, env=env)
    except FileNotFoundError:
        raise ValueError('git-sync guard: git is not installed or not in PATH') from None


def git(vault, *args):
    result = git_run(vault, *args)
    if result.returncode:
        raise ValueError('git-sync guard: git ' + args[0] + ' failed: ' + result.stderr.strip())
    return result.stdout


def git_sync_guard(vault, continue_batch=False, now=None):
    """Offline check that this clone cannot allocate an ID another machine already used.

    Never fetches: it relies on the operator's recent, successful `git fetch`/`git pull`.
    A vault without .git is refused unless APPROVED_INGEST_ALLOW_NO_GIT=1 (test sandboxes).
    """
    if not (vault / '.git').exists():
        if os.environ.get(ALLOW_NO_GIT) == '1':
            return {'git_guard': 'skipped-not-a-git-repo'}
        raise ValueError('git-sync guard: vault has no .git; publish only from a git clone of the vault')
    head = git_run(vault, 'symbolic-ref', '-q', 'HEAD')
    if head.returncode == 1:
        raise ValueError('git-sync guard: detached HEAD; check out main first')
    if head.returncode:
        raise ValueError('git-sync guard: git symbolic-ref failed: ' + head.stderr.strip())
    if head.stdout.strip() != 'refs/heads/main':
        raise ValueError('git-sync guard: current branch is not main; check out main first')
    # FETCH_HEAD lines are not bound to a remote here: with a second remote a mirror fetch could pass.
    if git(vault, 'remote').split() != ['origin']:
        raise ValueError('git-sync guard: vault must have exactly one remote, origin; adapt the guard first')
    upstream = git_run(vault, 'rev-parse', '--abbrev-ref', '@{u}')
    if upstream.returncode or upstream.stdout.strip() != UPSTREAM:
        raise ValueError(f'git-sync guard: branch must track {UPSTREAM}; publish only on main')
    # A failed fetch still truncates/touches FETCH_HEAD, and fetching another branch keeps it fresh:
    # require a recent FETCH_HEAD that records the upstream branch at the commit origin/main points to.
    fetch_head = Path(git(vault, 'rev-parse', '--path-format=absolute', '--git-path', 'FETCH_HEAD').strip())
    now = datetime.datetime.now().timestamp() if now is None else now
    # Negative age (future mtime: clock skew or manual touch) proves nothing about freshness.
    if not fetch_head.is_file() or not 0 <= now - fetch_head.stat().st_mtime <= FETCH_MAX_AGE:
        raise ValueError(f'git-sync guard: no git fetch in the last {FETCH_MAX_AGE // 60} min; '
                         'run `git fetch` (or `git pull`) first')
    tip = git(vault, 'rev-parse', '@{u}').strip()
    recorded = [line.split('\t', 2) for line in fetch_head.read_text(errors='replace').splitlines()]
    if not any(len(f) == 3 and f[0] == tip and f[2].startswith("branch 'main' of ") for f in recorded):
        raise ValueError('git-sync guard: last fetch does not match origin/main (failed fetch, other branch, or push since); '
                         'run `git fetch origin`')
    behind = int(git(vault, 'rev-list', '--count', 'HEAD..@{u}').strip())
    if behind:
        raise ValueError(f'git-sync guard: branch is {behind} commit(s) behind {UPSTREAM}; run `git pull` first')
    if git(vault, 'log', '--format=%h', '@{u}..HEAD', '--', *GUARDED).strip():
        raise ValueError('git-sync guard: unpushed commits touch notes/archive extracts/manifest/next-id/log; run `git push` first')
    dirty = git(vault, 'status', '--porcelain=v1', '--untracked-files=all', '--', *GUARDED).splitlines()
    if dirty and not continue_batch:
        raise ValueError(f'git-sync guard: {len(dirty)} uncommitted change(s) in notes/archive extracts/manifest/next-id/log; '
                         'commit and push them, or pass --continue-batch for the next note of the same approved batch')
    return {'git_guard': 'ok', 'upstream': UPSTREAM, 'uncommitted_in_batch': len(dirty)}


def validate_staging(vault, files):
    # Run the existing script in an isolated vault: it is NOT safe to import.
    with tempfile.TemporaryDirectory(prefix='approved-validation-') as tmp:
        stage = Path(tmp)
        for name, text in files.items():
            dest = stage / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(text, encoding='utf-8')
        for name in ('taxonomy.md', '90-meta/walidator.py'):
            shutil.copyfile(vault / name, stage / name)
        result = subprocess.run([sys.executable, str(stage / '90-meta/walidator.py')],
                                cwd=stage, capture_output=True, text=True)
        if result.returncode:
            raise ValueError('staging validation failed: ' + result.stdout + result.stderr)


def safe_path(vault, name):
    relative = Path(name)
    if relative.is_absolute() or '..' in relative.parts or str(relative) != name:
        raise ValueError('unsafe vault path: ' + name)
    target = vault
    for part in relative.parts:
        target = target / part
        if target.is_symlink():
            raise ValueError('symlink forbidden: ' + name)
    return target


@contextmanager
def vault_lock(vault):
    # Stable directory inode: replacing next-id cannot invalidate this lock.
    fd = os.open(safe_path(vault, '90-meta'), os.O_RDONLY | os.O_DIRECTORY)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('vault locked by another approved ingest') from None
        yield
    finally:
        os.close(fd)


def ingest(vault, data, check=False, continue_batch=False):
    with vault_lock(vault):
        return ingest_locked(vault, data, check, continue_batch)


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_write(target, content):
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.approved-', dir=target.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, target)
        sync_directory(target.parent)
    finally:
        Path(tmp).unlink(missing_ok=True)


JOURNAL = '00-archive/hermes/.approved-ingest-transaction.json'
STATUS_JOURNAL = '90-meta/.approved-status-transaction.json'  # owned by approved-status.py


def rollback(vault):
    journal = safe_path(vault, JOURNAL)
    entries = json.loads(journal.read_text())['entries']
    if len(entries) not in (4, 5) or not {'90-meta/manifest.jsonl', '90-meta/next-id'} <= entries.keys():
        raise ValueError('invalid transaction journal scope')
    decoded = []
    for name, entry in entries.items():
        target = safe_path(vault, name)
        if name not in ('90-meta/manifest.jsonl', '90-meta/next-id', 'log.md'):
            if not re.fullmatch(r'(00-archive/(hermes|inbox)/(sensitive/)?[0-9a-f]{32}\.md|10-notes/(sensitive/)?n-[0-9]{4,}-[a-z0-9ąćęłńóśźż-]+\.md)', name) or entry['before'] is not None:
                raise ValueError('invalid transaction journal target')
        old = base64.b64decode(entry['before'], validate=True) if entry['before'] is not None else None
        new = base64.b64decode(entry['after'], validate=True)
        current = target.read_bytes() if target.exists() else None
        if current not in (old, new):
            raise RuntimeError('recovery conflict: target changed outside transaction: ' + name)
        decoded.append((target, old, current))
    for target, old, current in reversed(decoded):
        if current == old:
            continue
        if old is None:
            target.unlink(missing_ok=True)
            sync_directory(target.parent)
        else:
            atomic_write(target, old)
    journal.unlink()
    sync_directory(journal.parent)


def recover(vault):
    with vault_lock(vault):
        if not (vault / JOURNAL).exists():
            return {'result': 'no-recovery-needed'}
        rollback(vault)
        return {'result': 'rolled-back'}


def publish(vault, files):
    entries = {}
    for name, text in files.items():
        target = vault / name
        old = target.read_bytes() if target.exists() else None
        entries[name] = {'before': base64.b64encode(old).decode() if old is not None else None,
                         'after': base64.b64encode(text.encode('utf-8')).decode()}
    journal = vault / JOURNAL
    atomic_write(journal, json.dumps({'entries': entries}).encode())
    try:
        for name, text in files.items():
            atomic_write(vault / name, text.encode('utf-8'))
        for name, text in files.items():
            if (vault / name).read_bytes() != text.encode('utf-8'):
                raise OSError('publication readback failed: ' + name)
    except BaseException as original:
        try:
            rollback(vault)
        except BaseException as failure:
            raise RuntimeError(f'recovery required: {original}; rollback failed: {failure}') from original
        raise
    journal.unlink()
    sync_directory(journal.parent)


def validation_report(vault):
    sources = {row.get('file') for line in (vault / '90-meta/manifest.jsonl').read_text().splitlines()
               if line.strip() for row in [json.loads(line)] if row.get('file')}
    unavailable = sorted(s for s in sources if not (vault / s).is_file())
    return {'scope': 'approved-note-only', 'full_vault_validated': False,
            'unavailable_sources': unavailable}


def ingest_locked(vault, data, check=False, continue_batch=False):
    if (vault / JOURNAL).exists():
        raise RuntimeError('recovery required: run --recover before ingest')
    if (vault / STATUS_JOURNAL).exists():
        raise RuntimeError('recovery required: run approved-status.py --recover before ingest')
    validate_payload(vault, data)
    report = validation_report(vault)
    prior = prior_result(vault, data)
    if prior:
        return dict(prior, validation=report)
    # After the idempotent rerun path: reruns of published payloads stay possible in a dirty batch.
    sync = git_sync_guard(vault, continue_batch)
    files, row = prepare(vault, data)
    for name in files:
        target = safe_path(vault, name)
        if name != 'log.md' and not name.startswith('90-meta/') and target.exists():
            raise ValueError('refusing to overwrite existing archive/note: ' + name)
    validate_staging(vault, files)
    if check:
        return dict(row, result='validated-not-published', validation=report, sync=sync)
    publish(vault, files)
    return dict(row, result='published', validation=report, sync=sync)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vault', type=Path, required=True)
    parser.add_argument('--check', action='store_true', help='stage and validate only; no writes to vault')
    parser.add_argument('--recover', action='store_true', help='roll back interrupted publication; no payload')
    parser.add_argument('--continue-batch', action='store_true',
                        help='allow uncommitted notes/manifest from earlier notes of the same approved batch')
    parser.add_argument('payload', type=Path, nargs='?')
    args = parser.parse_args()
    if args.check and args.recover:
        parser.error('--check cannot be combined with --recover')
    if args.continue_batch and args.recover:
        parser.error('--continue-batch cannot be combined with --recover')
    if args.recover == bool(args.payload):
        parser.error('provide either payload or --recover')
    try:
        result = recover(args.vault.resolve()) if args.recover else ingest(
            args.vault.resolve(), json.loads(args.payload.read_text()), args.check, args.continue_batch)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())

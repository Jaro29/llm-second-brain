#!/usr/bin/env python3
"""Offline, deterministic status change of an existing note, approved by the operator.

Changes ONLY `status` (resolved|superseded) and `superseded_by` in the note's frontmatter,
appends a {"kind": "status"} row to the manifest (append-only) and a line to log.md.
Same lock, git-sync guard, staging validation and rollback as approved-ingest.py.
See approved-ingest.md, section 'Zmiana statusu (approved-status)'.
"""
import argparse
import base64
import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys

import yaml

_spec = importlib.util.spec_from_file_location('approved_ingest', Path(__file__).with_name('approved-ingest.py'))
ai = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ai)

VERSION = 'approved-status-1.0'
STATUSES = ('resolved', 'superseded')
JOURNAL = ai.STATUS_JOURNAL  # approved-ingest refuses to run while this journal exists
NOTE_ID = re.compile(r'n-[0-9]{4,}')
NOTE_PATH = re.compile(r'10-notes/(sensitive/)?n-[0-9]{4,}-[a-z0-9ąćęłńóśźż-]+\.md')
CREDENTIAL = re.compile(r'(sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|'
                        r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY|(?i:bearer)\s+[A-Za-z0-9._-]{20,})')


def validate_payload(data):
    if set(data) != {'approval', 'note', 'status', 'superseded_by', 'powod'} or data['approval'] != 'approved':
        raise ValueError('explicit approval required; expected approval/note/status/superseded_by/powod')
    if not isinstance(data['note'], str) or not NOTE_ID.fullmatch(data['note']):
        raise ValueError('note must be n-XXXX')
    if data['status'] not in STATUSES:
        raise ValueError('status must be resolved or superseded')
    sb = data['superseded_by']
    if not isinstance(sb, str) or (sb and not NOTE_ID.fullmatch(sb)):
        raise ValueError('superseded_by must be n-XXXX or empty string')
    if data['status'] == 'superseded' and not sb:
        raise ValueError('superseded requires superseded_by')
    if data['status'] == 'resolved' and sb:
        raise ValueError('resolved must not set superseded_by')
    if sb == data['note']:
        raise ValueError('a note cannot supersede itself')
    if not isinstance(data['powod'], str) or len(data['powod'].strip()) < 10:
        raise ValueError('powod (reason) is required, at least 10 characters')
    # powod goes to log.md and the manifest, i.e. into git history: same conservative scan as approved-ingest.
    if CREDENTIAL.search(json.dumps(data, ensure_ascii=False)):
        raise ValueError('possible credential: change refused; review privately')


def find_note(vault, note_id):
    hits = [p for p in vault.glob('10-notes/**/*.md') if p.name.startswith(note_id + '-')]
    if len(hits) != 1:
        raise ValueError(f'note {note_id}: expected exactly one file, found {len(hits)}')
    name = str(hits[0].relative_to(vault))
    if not NOTE_PATH.fullmatch(name):
        raise ValueError('unexpected note path: ' + name)
    return name, ai.safe_path(vault, name)


def frontmatter(text):
    if not text.startswith('---\n') or '\n---\n' not in text[4:]:
        raise ValueError('note has no frontmatter')
    raw, body = text[4:].split('\n---\n', 1)
    return raw, body


def manifest_rows(vault):
    return [json.loads(line) for line in (vault / '90-meta/manifest.jsonl').read_text().splitlines() if line.strip()]


def edit_frontmatter(text, status, superseded_by):
    """Line-level edit: the rest of the note stays byte-identical (no YAML re-dump)."""
    raw, body = frontmatter(text)
    new = raw
    for key, value in (('status', status), ('superseded_by', superseded_by or 'null')):
        new, n = re.subn(rf'^{key}: .*$', f'{key}: {value}', new, count=1, flags=re.M)
        if n != 1:
            raise ValueError(f'note frontmatter has no single top-level `{key}:` line')
    before, after = yaml.safe_load(raw), yaml.safe_load(new)
    changed = {k for k in set(before) | set(after) if before.get(k) != after.get(k)}
    if not changed <= {'status', 'superseded_by'} or after['status'] != status \
            or after['superseded_by'] != (superseded_by or None):
        raise ValueError('frontmatter edit touched more than status/superseded_by')
    return '---\n' + new + '\n---\n' + body


def prepare(vault, data):
    name, path = find_note(vault, data['note'])
    text = path.read_text(encoding='utf-8')
    meta = yaml.safe_load(frontmatter(text)[0])
    if meta.get('id') != data['note']:
        raise ValueError('note id in frontmatter does not match')
    if meta['status'] in ('superseded', 'evergreen'):
        raise ValueError(f'note {data["note"]} is {meta["status"]}; change refused')
    if meta['status'] == data['status']:
        raise ValueError(f'note {data["note"]} already has status {data["status"]}')
    if data['superseded_by']:
        target_name, target = find_note(vault, data['superseded_by'])
        target_meta = yaml.safe_load(frontmatter(target.read_text(encoding='utf-8'))[0])
        if target_meta.get('status') == 'superseded':
            raise ValueError(f'superseded_by {data["superseded_by"]} is itself superseded; point to the current note')
        if target_meta.get('sensitive') and not meta.get('sensitive'):
            raise ValueError('a public note cannot point to a sensitive note')
    new_text = edit_frontmatter(text, data['status'], data['superseded_by'])
    now = datetime.datetime.now(datetime.UTC).isoformat(timespec='seconds')
    row = {'kind': 'status', 'note': data['note'], 'note_file': name, 'from': meta['status'],
           'to': data['status'], 'superseded_by': data['superseded_by'] or None, 'powod': data['powod'].strip(),
           'approval_hash': ai.approval_hash(data), 'ingest_version': VERSION,
           'note_sha256_before': hashlib.sha256(text.encode('utf-8')).hexdigest(),
           'note_sha256': hashlib.sha256(new_text.encode('utf-8')).hexdigest(), 'processed_at': now}
    manifest = (vault / '90-meta/manifest.jsonl').read_bytes().decode('utf-8')
    if manifest and not manifest.endswith('\n'):
        manifest += '\n'
    log_path = ai.safe_path(vault, 'log.md')
    log = log_path.read_bytes().decode('utf-8') if log_path.exists() else ''
    if log and not log.endswith('\n'):
        log += '\n'
    target = f' -> {data["superseded_by"]}' if data['superseded_by'] else ''
    log += (f'\n## [{now[:10]}] approved-status | {now} {VERSION}: {data["note"]} '
            f'{meta["status"]} -> {data["status"]}{target}; {row["powod"]}\n')
    files = {name: new_text, '90-meta/manifest.jsonl': manifest + json.dumps(row, ensure_ascii=False) + '\n',
             'log.md': log}
    return files, row, meta


def prior_result(vault, data):
    matches = [r for r in manifest_rows(vault) if r.get('kind') == 'status'
               and r.get('approval_hash') == ai.approval_hash(data)]
    if not matches:
        return None
    row = matches[-1]
    note = ai.safe_path(vault, row['note_file'])
    if not note.is_file() or hashlib.sha256(note.read_bytes()).hexdigest() != row['note_sha256']:
        raise ValueError('note drift: changed after the recorded status change')
    return dict(row, result='already-done')


def validate_staging(vault, files, meta, data):
    # Staged vault = changed files + what the walidator cross-checks: next-id, source extract, target note.
    # An archive file outside git (00-archive/) may be missing on this clone; the status change does not touch it,
    # so a placeholder lives ONLY in the staging copy and the gap is reported, as approved-ingest does.
    staged = dict(files)
    staged['90-meta/next-id'] = (vault / '90-meta/next-id').read_text()
    extra = [(meta.get('source') or {}).get('file')]
    if data['superseded_by']:
        target = find_note(vault, data['superseded_by'])[0]
        target_meta = yaml.safe_load(frontmatter((vault / target).read_text(encoding='utf-8'))[0])
        extra += [target, (target_meta.get('source') or {}).get('file')]
    unavailable = []
    for name in filter(None, extra):
        if (vault / name).is_file():
            staged[name] = (vault / name).read_text(encoding='utf-8')
        elif name.startswith('00-archive/'):
            staged[name] = '(placeholder: source archive not present on this clone)\n'
            unavailable.append(name)
    ai.validate_staging(vault, staged)
    return {'scope': 'status-change-only', 'unavailable_sources': unavailable}


def rollback(vault):
    journal = ai.safe_path(vault, JOURNAL)
    entries = json.loads(journal.read_text())['entries']
    notes = [n for n in entries if n not in ('90-meta/manifest.jsonl', 'log.md')]
    if len(entries) != 3 or '90-meta/manifest.jsonl' not in entries or len(notes) != 1 \
            or not NOTE_PATH.fullmatch(notes[0]):
        raise ValueError('invalid status transaction journal scope')
    decoded = []
    for name, entry in entries.items():
        target = ai.safe_path(vault, name)
        if entry['before'] is None and name != 'log.md':
            raise ValueError('invalid status transaction journal target')
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
        else:
            ai.atomic_write(target, old)
    journal.unlink()
    ai.sync_directory(journal.parent)


def publish(vault, files):
    entries = {}
    for name, text in files.items():
        target = vault / name
        old = target.read_bytes() if target.exists() else None
        entries[name] = {'before': base64.b64encode(old).decode() if old is not None else None,
                         'after': base64.b64encode(text.encode('utf-8')).decode()}
    journal = vault / JOURNAL
    ai.atomic_write(journal, json.dumps({'entries': entries}).encode())
    try:
        for name, text in files.items():
            ai.atomic_write(vault / name, text.encode('utf-8'))
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
    ai.sync_directory(journal.parent)


def change_locked(vault, data, check=False, continue_batch=False):
    for j in (JOURNAL, ai.JOURNAL):
        if (vault / j).exists():
            raise RuntimeError(f'recovery required ({j}): run --recover first')
    validate_payload(data)
    prior = prior_result(vault, data)
    if prior:
        return prior
    sync = ai.git_sync_guard(vault, continue_batch)
    files, row, meta = prepare(vault, data)
    validation = validate_staging(vault, files, meta, data)
    if check:
        return dict(row, result='validated-not-published', sync=sync, validation=validation)
    publish(vault, files)
    return dict(row, result='published', sync=sync, validation=validation)


def change(vault, data, check=False, continue_batch=False):
    with ai.vault_lock(vault):
        return change_locked(vault, data, check, continue_batch)


def recover(vault):
    with ai.vault_lock(vault):
        if not (vault / JOURNAL).exists():
            return {'result': 'no-recovery-needed'}
        rollback(vault)
        return {'result': 'rolled-back'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vault', type=Path, required=True)
    parser.add_argument('--check', action='store_true', help='stage and validate only; no writes to vault')
    parser.add_argument('--recover', action='store_true', help='roll back interrupted status change; no payload')
    parser.add_argument('--continue-batch', action='store_true',
                        help='allow uncommitted changes from earlier items of the same approved batch')
    parser.add_argument('payload', type=Path, nargs='?')
    args = parser.parse_args()
    if args.recover and (args.check or args.continue_batch):
        parser.error('--recover cannot be combined with --check/--continue-batch')
    if args.recover == bool(args.payload):
        parser.error('provide either payload or --recover')
    try:
        vault = args.vault.resolve()
        result = recover(vault) if args.recover else change(
            vault, json.loads(args.payload.read_text()), args.check, args.continue_batch)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())

"""Private workspace persistence. No GitHub or rendering dependencies."""
from contextlib import contextmanager
import copy
import fcntl
import hashlib
import json
import re
import threading
import uuid
import pr_review_tracker as tracker

_lock = threading.RLock()
_NOTE_ID = re.compile(r'^[A-Za-z0-9_-]{8,80}$')


def note_id(value):
    return value if isinstance(value, str) and _NOTE_ID.fullmatch(value) else ''


def _contexts(note):
    contexts = note.get('contexts')
    if isinstance(contexts, list):
        return contexts
    context = note.get('context')
    return [context] if isinstance(context, dict) else []


def _revision_metadata(note):
    base = note.get('base') if isinstance(note.get('base'), str) else ''
    head = note.get('head') if isinstance(note.get('head'), str) else ''
    for context in _contexts(note):
        if not isinstance(context, dict):
            continue
        if not base and isinstance(context.get('base'), str):
            base = context['base']
        if not head and isinstance(context.get('head'), str):
            head = context['head']
    return base, head


def normalize_notes(notes, previous=None):
    """Give notes durable identities while keeping old state readable."""
    previous = previous if isinstance(previous, list) else []
    normalized = []
    used = set()
    changed = False
    for index, value in enumerate(notes):
        if not isinstance(value, dict):
            normalized.append(copy.deepcopy(value))
            continue
        note = copy.deepcopy(value)
        old = previous[index] if index < len(previous) and isinstance(previous[index], dict) else {}
        candidate = note_id(note.get('id'))
        if not candidate or candidate in used:
            candidate = note_id(old.get('id')) if note_id(old.get('id')) not in used else ''
            note['id'] = candidate or str(uuid.uuid4())
            changed = True
        used.add(note['id'])
        if not isinstance(note.get('created_at'), str) or not note['created_at']:
            note['created_at'] = old.get('created_at') if isinstance(old.get('created_at'), str) and old['created_at'] else tracker.utc_now()
            changed = True
        base, head = _revision_metadata(note)
        if base and note.get('base') != base:
            note['base'] = base
            changed = True
        if head and note.get('head') != head:
            note['head'] = head
            changed = True
        normalized.append(note)
    return normalized, changed


def directory(url):
    canonical, *_ = tracker.canonical_pr_url(url)
    root = tracker.tracker_root() / 'workspaces' / hashlib.sha256(canonical.encode()).hexdigest()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    return root


@contextmanager
def locked(url):
    with _lock, (directory(url) / 'state.lock').open('a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def read(url):
    value = tracker.read_json(directory(url) / 'state.json', required=False)
    return {'version': 0, 'viewed': {}, 'collapsed': [], 'notes': [], 'attachments': {}, **value}


def ensure_note_metadata(url):
    """Migrate legacy notes once, so every client can refer to a stable ID."""
    with locked(url):
        state = read(url)
        notes, changed = normalize_notes(state.get('notes', []), state.get('notes', []))
        if changed:
            state['notes'] = notes
            state = write(url, state)
        return state


def write(url, state):
    state['version'] += 1
    tracker.atomic_write(directory(url) / 'state.json', state)
    return state


def reconcile(url, manifest):
    """Preserve viewed files only when both sides of their comparison match."""
    with locked(url):
        state = read(url)
        fingerprints = {f['path']: f['fingerprint'] for f in manifest['files']}
        viewed = {p: digest for p, digest in state['viewed'].items() if fingerprints.get(p) == digest}
        if state.get('revision') != manifest['revision'] or viewed != state['viewed']:
            state.update(viewed=viewed, revision=manifest['revision'])
            write(url, state)
        return state


def save(url, manifest, request):
    with locked(url):
        state = read(url)
        if request.get('version') != state['version']:
            raise ValueError('This workspace changed in another tab. Reload before saving more changes.')
        valid = {f['path']: f['fingerprint'] for f in manifest['files']}
        viewed, collapsed, notes = (request.get(k) for k in ('viewed', 'collapsed', 'notes'))
        if not all(isinstance(v, list) for v in (viewed, collapsed, notes)):
            raise ValueError('Invalid workspace state.')
        if len(notes) > 500 or len(json.dumps(notes)) > 500_000:
            raise ValueError('Private notes exceed the workspace limit.')
        for note in notes:
            if not isinstance(note, dict) or not isinstance(note.get('text'), str) or len(note['text']) > 50_000:
                raise ValueError('Invalid note.')
        notes, _ = normalize_notes(notes, state.get('notes', []))
        attachments = request.get('attachments', {})
        if not isinstance(attachments, dict) or len(json.dumps(attachments)) > 100_000:
            raise ValueError('Too many code attachments.')
        if request.get('revision') == state.get('revision'):
            state.update(viewed={p: valid[p] for p in viewed if isinstance(p, str) and p in valid},
                         collapsed=[p for p in collapsed if isinstance(p, str) and p in valid])
        # Historical chats/notes remain editable without rewriting current progress.
        state.update(notes=notes, attachments=attachments)
        return write(url, state)

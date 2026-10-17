#!/usr/bin/env python3
"""Render inert authoring JSON and exact Git excerpts into one offline HTML page."""
import argparse
import base64
import hashlib
import html
import itertools
from html.parser import HTMLParser
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
from urllib.parse import quote, urlsplit, unquote
from pr_dashboard import markdown_inline_to_html
from review_markdown import render as render_markdown
from review_diagram import sanitize as sanitize_diagram
import review_mermaid
from validate_review_notes import validate
import review_verdict
import pr_review_tracker as tracker

FINDING_OPEN = '<details class="review-finding">'
VERDICT_SIDECAR = 'review-verdict.json'
ASSETS = Path(__file__).resolve().parent.parent / 'assets'
CSP = "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src data:; connect-src 'none'; font-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'"

def esc(value):
    return html.escape(str(value), quote=True)

class OverviewWords(HTMLParser):
    """Estimate prose outside optional disclosures and code, not review duration."""
    excluded = {'details', 'pre', 'textarea', 'script', 'style'}

    def __init__(self):
        super().__init__()
        self.hidden_depth = 0
        self.sections = []
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag == 'section':
            self.sections.append(dict(attrs).get('id') == 'review-findings')
            self.hidden_depth += self.sections[-1]
        if tag in self.excluded:
            self.hidden_depth += 1

    def handle_endtag(self, tag):
        if tag == 'section':
            self.hidden_depth -= self.sections.pop()
        if tag in self.excluded:
            self.hidden_depth -= 1

    def handle_data(self, data):
        if not self.hidden_depth:
            self.parts.append(data)

    def count(self, content):
        self.feed(content)
        return len(' '.join(self.parts).split())

def url(value):
    parsed = urlsplit(value)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or any(ord(c) < 32 for c in value):
        raise ValueError('Links must be verified HTTPS URLs without credentials')
    return value

def anchor(label, target):
    return f'<a href="{esc(url(target))}" target="_blank" rel="noopener noreferrer">{esc(label)}</a>'

def attachment_urls(data):
    result = {}
    root = tracker.tracker_root().resolve()
    for value in data.get('attachments', []):
        p = Path(value).expanduser().resolve(strict=True)
        if not p.is_relative_to(root) or not p.is_file() or p.suffix.lower() not in {'.md', '.txt', '.log', '.png', '.jpg', '.jpeg', '.webp'}:
            raise ValueError('Attachments must be existing tracker evidence files')
        result[str(p)] = p.as_uri()
    return result

def review_inline(data):
    attachments = attachment_urls(data)
    def inline(value):
        rendered = markdown_inline_to_html(value)
        def link(match):
            target = html.unescape(match[1])
            if target.startswith('/artifact?path='):
                local = str(Path(unquote(target.split('=', 1)[1])).resolve())
                if local not in attachments:
                    raise ValueError('Local evidence link must be listed in attachments')
                target = attachments[local]
            else:
                target = url(target)
            return f'<a href="{esc(target)}" target="_blank" rel="noopener noreferrer">{match[2]}</a>'
        return re.sub(r'<a href="([^"<>]*)"[^>]*>(.*?)</a>', link, rendered)
    return inline

def comment_footer(data):
    """The on-behalf line appended to every draft comment, e.g. *Posted by Codex (gpt-6-astra) on Robert's behalf.*"""
    value = data.get('comment_attribution')
    if value is None: return ''
    if not isinstance(value, dict) or set(value) - {'tool', 'model', 'person'}:
        raise ValueError('comment_attribution takes tool, model and person')
    for key in value:
        if not isinstance(value[key], str) or not re.fullmatch(r"(?:[^\W_]|[ .'-]){0,60}", value[key]):
            raise ValueError('comment_attribution values must be short plain text')
    tool, model, person = (value.get(key, '').strip() for key in ('tool', 'model', 'person'))
    if not tool or not person: raise ValueError('comment_attribution needs tool and person')
    return f"*Posted by {tool}{f' ({model})' if model else ''} on {person}'s behalf.*"

def review_markdown(text, data):
    inline = review_inline(data)
    def visual(key):
        value = data.get('review', {}).get('visuals', {}).get(key)
        if not isinstance(value, dict) or value.get('type') not in VISUAL_TYPES:
            raise ValueError('Review visual must reference a defined diagram, cases, table, flow, sequence, scenario or stepper')
        return blocks([value], data)
    return render_markdown(text, inline, esc, visual=visual, footer=comment_footer(data))

def git(repository, *args):
    return subprocess.check_output(['git', '-C', str(repository), *args], text=True)

def source_path(value):
    p = PurePosixPath(value)
    if p.is_absolute() or '..' in p.parts or not value or any(ord(c) < 32 for c in value):
        raise ValueError('Source paths must be repository-relative')
    return value

def preflight_blobs(data):
    """Avoid lazy network fetches and opaque Git errors for offline excerpt clones."""
    repository = data['repository']
    config = subprocess.run(['git', '-C', repository, 'config', '--get-regexp',
                             r'remote\..*\.partialclonefilter'], capture_output=True, text=True)
    if not any(line.endswith(' blob:none') for line in config.stdout.splitlines()): return
    paths = set()
    def visit(value):
        if isinstance(value, dict):
            if value.get('type') == 'source': paths.add(source_path(value['path']))
            for child in value.values(): visit(child)
        elif isinstance(value, list):
            for child in value: visit(child)
    visit(data.get('sections', [])); visit(data.get('review', {}).get('visuals', {}))
    for revision in (data['base'], data['head']):
        if revision == 'working-tree': continue
        for path in sorted(paths):
            oid = subprocess.run(['git', '-C', repository, 'rev-parse', f'{revision}:{path}'],
                                 capture_output=True, text=True, env={**os.environ, 'GIT_NO_LAZY_FETCH': '1'})
            if oid.returncode: continue  # A genuinely absent path retains its normal error.
            blob = subprocess.run(['git', '-C', repository, 'cat-file', '-e', oid.stdout.strip()],
                                  capture_output=True, env={**os.environ, 'GIT_NO_LAZY_FETCH': '1'})
            if blob.returncode:
                raise ValueError('repository is a blobless partial clone; point at a full or --shared clone')

def file_status(data, path):
    args = ['diff', '--no-ext-diff', '--no-renames', '--name-status', data['base']]
    if data['head'] != 'working-tree':
        args.append(data['head'])
    status = git(Path(data['repository']), *args, '--', path).split('\t', 1)[0][:1]
    return {'A': 'new', 'D': 'removed', '': 'unchanged'}.get(status, 'changed')

def line_changes(repository, base, head, path, side):
    args = ['diff', '--no-ext-diff', '--no-textconv', '--unified=0', base]
    if head != 'working-tree':
        args.append(head)
    text = git(repository, *args, '--', path)
    numbers = set()
    for line in text.splitlines():
        m = re.match(r'@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@', line)
        if m:
            offset = 0 if side == 'base' else 2
            start = int(m[offset + 1]); count = int(m[offset + 2] or '1')
            numbers.update(range(start, start + count))
    return numbers

KEYWORDS = set('abstract as async await bool break case catch class const continue default do double else enum export extends false final finally for from function if implements import in int interface is let new null of on override private protected public return static String super switch this throw true try type typeof var void while with yield'.split())
TOKEN = re.compile(r'(?P<comment>//[^\n]*|/\*.*?\*/)|(?P<string>"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|`(?:\\.|[^`\\])*`)|(?P<word>\b[A-Za-z_$][\w$]*\b)|(?P<number>\b\d+(?:\.\d+)?\b)', re.S)

def highlight(text, language):
    if language not in {'Dart', 'TypeScript', 'JavaScript', 'Go', 'Swift', 'Java', 'Kotlin', 'JSON'}:
        return esc(text)
    parts = []; end = 0
    for match in TOKEN.finditer(text):
        parts.append(esc(text[end:match.start()])); token = match.group()
        kind = match.lastgroup
        if kind == 'word':
            kind = 'keyword' if token in KEYWORDS else None
        parts.append(f'<span class="token-{kind}">{esc(token)}</span>' if kind else esc(token))
        end = match.end()
    parts.append(esc(text[end:])); return ''.join(parts)

LANGUAGES = {'.dart':'Dart','.ts':'TypeScript','.tsx':'TypeScript','.js':'JavaScript','.jsx':'JavaScript','.go':'Go','.swift':'Swift','.java':'Java','.kt':'Kotlin','.json':'JSON','.py':'Python','.tf':'Terraform','.md':'Markdown'}

def source(block, data):
    path = source_path(block['path']); side = block.get('side', 'head')
    if side not in {'base', 'head'}:
        raise ValueError('Source side must be base or head')
    revision = data[side]; repository = Path(data['repository'])
    if revision == 'working-tree':
        f = (repository / path).resolve()
        if not f.is_relative_to(repository.resolve()):
            raise ValueError('Working-tree file escapes repository')
        raw = f.read_text()
    else:
        raw = git(repository, 'show', f'{revision}:{path}')
    lines = raw.splitlines(); start = block['start']; end = block['end']
    if not isinstance(start, int) or not isinstance(end, int) or not 1 <= start <= end <= len(lines):
        raise ValueError(f'Invalid source range for {path}: {start}-{end}')
    if end - start + 1 > 15:
        raise ValueError('Select source ranges of at most 15 lines')
    changed = line_changes(repository, data['base'], data['head'], path, side)
    language = LANGUAGES.get(Path(path).suffix, 'Plain text')
    rows = []
    for n in range(start, end + 1):
        state = ('removed' if side == 'base' else 'added') if n in changed else 'context'
        marker = {'removed':'−','added':'+','context':' '}[state]
        rows.append(f'<span class="code-line {state}" data-line="{n}"><span class="gutter" aria-hidden="true">{marker} {n}</span><span class="source-text">{highlight(lines[n-1],language)}</span></span>')
    links = ''
    if revision != 'working-tree' and data.get('repo_url'):
        links += anchor('Pinned source', f'{data["repo_url"]}/blob/{revision}/{quote(path, safe="/")}#L{start}-L{end}')
        if data.get('pr_url') and changed.intersection(range(start,end+1)):
            first = min(changed.intersection(range(start,end+1)))
            links += anchor('PR diff', f'{data["pr_url"]}/files#diff-{hashlib.sha256(path.encode()).hexdigest()}{"L" if side == "base" else "R"}{first}')
    title = f'{language} · {side} · lines {start}–{end}'
    return f'<figure class="source" data-path="{esc(path)}" data-revision="{esc(revision)}" data-side="{side}"><div class="source-meta"><span class="path">{esc(path)}</span><span>{esc(title)}</span>{links}</div><pre><code>{"".join(rows)}</code></pre><figcaption class="caption">{esc(block["caption"])}</figcaption></figure>'

ICONS = {
    'app': '<rect x="5" y="3" width="22" height="26" rx="4"/><path d="M12 24h8"/>',
    'memory': '<rect x="5" y="7" width="22" height="18" rx="2"/><path d="M10 3v4m6-4v4m6-4v4M10 25v4m6-4v4m6-4v4M10 12h12m-12 5h12"/>',
    'storage': '<ellipse cx="16" cy="7" rx="11" ry="4"/><path d="M5 7v18c0 5 22 5 22 0V7M5 16c0 5 22 5 22 0"/>',
    'network': '<path d="M9 25h15a6 6 0 0 0 1-12 9 9 0 0 0-17-2 7 7 0 0 0 1 14"/>',
}

VISUAL_TYPES = {'diagram', 'cases', 'table', 'flow', 'sequence', 'scenario', 'mermaid', 'compare', 'callouts', 'stepper'}
CASE_MARKS = {'works': ('✅', 'Works'), 'breaks': ('❌', 'Breaks'), 'changes': ('⚠️', 'Changes'), 'same': ('', ''), 'unknown': ('❔', 'Not established'), 'absent': ('—', 'Not available')}

def diagram(block):
    title = f'<figcaption class="diagram-title">{esc(block["title"])}</figcaption>' if block.get('title') else ''
    return (f'<figure class="diagram">{title}<div class="diagram-body">{sanitize_diagram(block["html"])}</div>'
            f'<p class="caption">{esc(block["caption"])}</p></figure>')

def cases(block, paper=False):
    columns = block['columns']
    if not 2 <= len(columns) <= 5:
        raise ValueError('A cases grid needs a situation column and one to four outcome columns')
    rows = block['rows']
    if not 1 <= len(rows) <= 8:
        raise ValueError('A cases grid needs one to eight situations')
    body = []
    for row in rows:
        cells = row['cells']
        if len(cells) != len(columns) - 1:
            raise ValueError('Each cases row needs one cell per outcome column')
        badge = f' <span class="case-finding">⚠ {esc(row["finding"])}</span>' if row.get('finding') else ''
        out = [f'<th scope="row">{esc(row["situation"])}{badge}</th>']
        for index, cell in enumerate(cells, 1):
            status = cell.get('status', 'same')
            if status not in CASE_MARKS:
                raise ValueError('Cases status must be works, breaks, changes, same, unknown or absent')
            mark, word = CASE_MARKS[status]
            prefix = (f'<span class="case-status">{word}</span>: ' if status == 'absent' else f'<span class="case-mark" aria-hidden="true">{mark}</span><span class="visually-hidden">{word}: </span>' if mark else '')
            label = f' data-label="{esc(columns[index])}"' if paper else ''
            out.append(f'<td class="case-{status}"{label}>{prefix}{esc(cell["text"])}</td>')
        body.append('<tr>' + ''.join(out) + '</tr>')
    headers = ''.join(f'<th scope="col">{esc(x)}</th>' for x in columns)
    title = f'<figcaption class="diagram-title">{esc(block["title"])}</figcaption>' if block.get('title') else ''
    return (f'<figure class="cases">{title}<p class="table-hint">Scroll the table horizontally if needed.</p>'
            f'<div class="table-scroll" tabindex="0" role="region" aria-label="{esc(block.get("title") or "Situations")}">'
            f'<table><thead><tr>{headers}</tr></thead><tbody>{"".join(body)}</tbody></table></div>'
            f'<p class="caption">{esc(block["caption"])}</p></figure>')

# Walk blocks: inspired by annanay25/explain-pr's visual language (no code copied).
def mermaid(block, data):
    svg = data['_mermaid'].get(review_mermaid.diagram_id(block['source']))
    if svg is None:
        raise ValueError('Mermaid diagrams are rendered before the page')
    title = f'<p class="walk-eyebrow">{esc(block["title"])}</p>' if block.get('title') else ''
    notes = block.get('notes') or {}
    if not isinstance(notes, dict) or not all(isinstance(v, str) for v in notes.values()):
        raise ValueError('Mermaid notes map a participant label to one sentence')
    facts = ''.join(f'<div data-participant="{esc(k)}">{esc(v)}</div>' for k, v in notes.items())
    facts = f'<div class="mermaid-notes" hidden>{facts}</div>' if facts else ''
    caption = f'<p class="caption">{esc(block["caption"])}</p>' if block.get('caption') else ''
    return f'<figure class="mermaid-figure">{title}<div class="mermaid-body">{svg}</div>{facts}{caption}</figure>'

CARD_ICONS = {
    'type': '<rect x="4" y="5" width="16" height="14" rx="2"/><path d="M8 9h8M8 12h8M8 15h5"/>',
    'branch': '<circle cx="6" cy="6" r="2"/><circle cx="6" cy="18" r="2"/><circle cx="18" cy="9" r="2"/><path d="M6 8v8M8 6h4a4 4 0 0 1 4 3"/>',
    'lock': '<rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>',
    'fn': '<path d="M14 4h-1a3 3 0 0 0-3 3v10a3 3 0 0 1-3 3H6M7 11h7"/>',
    'db': '<ellipse cx="12" cy="6" rx="7" ry="2.5"/><path d="M5 6v12c0 1.4 3.1 2.5 7 2.5s7-1.1 7-2.5V6M5 12c0 1.4 3.1 2.5 7 2.5s7-1.1 7-2.5"/>',
    'event': '<path d="M4 6h16M4 12h10M4 18h7"/><circle cx="18" cy="16" r="3"/>',
    'check': '<circle cx="12" cy="12" r="8"/><path d="m8.5 12 2.5 2.5 4.5-5"/>',
    'pipe': '<path d="M3 8h6l3 4-3 4H3M12 12h9"/>',
    'flag': '<path d="M6 21V4M6 4h11l-2 4 2 4H6"/>',
    'api': '<path d="M12 3 21 12 12 21 3 12z"/><circle cx="12" cy="12" r="2.5"/>',
    'config': '<path d="M4 7h10M18 7h2M4 17h4M12 17h8"/><circle cx="16" cy="7" r="2"/><circle cx="10" cy="17" r="2"/>',
    'test': '<path d="M9 3h6M10 3v6l-5 9a2 2 0 0 0 2 3h10a2 2 0 0 0 2-3l-5-9V3"/>',
    'user': '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
    'server': '<rect x="4" y="4" width="16" height="7" rx="1.5"/><rect x="4" y="13" width="16" height="7" rx="1.5"/><path d="M8 7.5h.01M8 16.5h.01"/>',
    'file': '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/>',
    'thread': '<path d="M4 6c4 0 4 4 8 4s4-4 8-4M4 12c4 0 4 4 8 4s4-4 8-4"/>',
    'box': '<rect x="4" y="4" width="16" height="16" rx="3"/>',
}
CARD_TAGS = {'new': 'new', 'changed': 'changed', 'removed': 'removed', 'existing': 'existed'}
TONES = {'before', 'after', 'safe', 'risk', 'neutral'}
CALLOUT_TONES = {'good', 'warn', 'bad', 'plain'}

def finding_badge(label):
    return f'<span class="walk-finding">⚠ {esc(label)}</span>' if label else ''

def card(block):
    icon = block.get('icon', 'box')
    if icon not in CARD_ICONS:
        raise ValueError(f'Card icon must be one of {", ".join(CARD_ICONS)}')
    tag = block.get('tag')
    if tag is not None and tag not in CARD_TAGS:
        raise ValueError('Card tag must be new, changed, removed or existing')
    tone = block.get('tone', '')
    if tone not in {'', 'hot', 'gate'}:
        raise ValueError('Card tone must be hot or gate')
    classes = ' '.join(x for x in ['walk-card', f'tag-{tag}' if tag else '', f'tone-{tone}' if tone else ''] if x)
    label = f'<span class="walk-tag">{CARD_TAGS[tag]}</span>' if tag else ''
    kind = f'<p class="walk-kind">{esc(block["kind"])}</p>' if block.get('kind') else ''
    return (f'<div class="{classes}"><span class="walk-icon"><svg viewBox="0 0 24 24" aria-hidden="true">{CARD_ICONS[icon]}</svg></span>'
            f'<div>{kind}<strong>{esc(block["name"])}</strong><p>{esc(block.get("role", ""))}</p>{finding_badge(block.get("finding"))}</div>{label}</div>')

def callouts(block):
    items = []
    for item in block['items']:
        tone = item.get('tone', 'plain')
        if tone not in CALLOUT_TONES:
            raise ValueError('Callout tone must be good, warn, bad or plain')
        title = f'<strong>{esc(item["title"])}</strong> ' if item.get('title') else ''
        items.append(f'<div class="walk-callout tone-{tone}">{title}{esc(item["text"])} {finding_badge(item.get("finding"))}</div>')
    return f'<div class="walk-callouts">{"".join(items)}</div>'

def compare(block, data):
    panes = block['panes']
    if not 1 <= len(panes) <= 3:
        raise ValueError('A compare block needs one to three panes')
    out = []
    for pane in panes:
        tone = pane.get('tone', 'neutral')
        if tone not in TONES:
            raise ValueError('Pane tone must be before, after, safe, risk or neutral')
        out.append(f'<div class="walk-pane tone-{tone}"><p class="walk-eyebrow">{esc(pane["label"])}</p><div class="walk-stack">{blocks(pane["blocks"], data)}</div></div>')
    layout = 'stacked' if block.get('stacked') else f'cols-{len(panes)}'
    caption = f'<p class="caption">{esc(block["caption"])}</p>' if block.get('caption') else ''
    return f'<div class="walk-compare {layout}">{"".join(out)}</div>{caption}'

def pair(block, data):
    left = f'<div class="walk-callout tone-plain">{esc(block["change"])}</div>' + blocks(block.get('blocks', []), data)
    if not block.get('diff'):
        raise ValueError('A pair needs diff blocks (source or example)')
    if any(b.get('type') not in {'source', 'example', 'paragraph'} for b in block['diff']):
        raise ValueError('Pair diff blocks are source, example or paragraph')
    return (f'<div class="walk-pair"><div class="walk-pane"><p class="walk-eyebrow">{esc(block.get("label", "Logical change"))}</p><div class="walk-stack">{left}</div></div>'
            f'<div class="walk-pane"><p class="walk-eyebrow">Important diff</p><div class="walk-stack">{blocks(block["diff"], data)}</div></div></div>')

def text_field(value, label, words=None, sentences=None):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{label} must be non-empty text')
    if words and len(value.split()) > words:
        raise ValueError(f'{label} must be at most {words} words')
    if sentences and len(re.split(r'(?<=[.!?])\s+', value.strip())) > sentences:
        raise ValueError(f'{label} must be at most {sentences} sentence(s)')
    return value


def object_fields(value, allowed, label):
    if not isinstance(value, dict) or set(value) - set(allowed.split()):
        raise ValueError(f'{label} must be an object with fields: {allowed}')


def finding_number(value, count):
    if not isinstance(value, str) or not re.fullmatch(r'(?:Finding |finding-)[1-9][0-9]*', value):
        raise ValueError('finding must name Finding N or finding-N')
    number = int(re.search(r'[0-9]+$', value)[0])
    if number > count:
        raise ValueError('finding must reference an existing finding')
    return number


def code_walk(block, data):
    object_fields(block, 'type example items', 'code_walk')
    items = block.get('items')
    if not isinstance(items, list) or not 2 <= len(items) <= 6:
        raise ValueError('A code_walk needs two to six items')
    example = f'<p>{esc(text_field(block["example"], "code_walk example"))}</p>' if 'example' in block else ''
    rows = []
    for item in items:
        object_fields(item, 'path tag text diff', 'code_walk item')
        path = source_path(text_field(item.get('path'), 'code_walk path'))
        if 'tag' in item and (not isinstance(item['tag'], str) or item['tag'] not in {'new', 'changed', 'removed', 'unchanged'}):
            raise ValueError('code_walk tag must be new, changed, removed or unchanged')
        # Git decides the badge, so a context file is never shown as changed.
        tag = file_status(data, path)
        text_field(unnumbered(item.get('text')), 'code_walk text', sentences=1)
        diff = item.get('diff')
        if not isinstance(diff, list) or not diff or any(not isinstance(b, dict) or not isinstance(b.get('type'), str) or b['type'] not in {'source', 'example'} for b in diff):
            raise ValueError('code_walk diff needs source or example blocks')
        seen_paths = {path}
        excerpts = []
        for excerpt in diff:
            if 'open' in excerpt and not isinstance(excerpt['open'], bool):
                raise ValueError('code_walk excerpt open must be true or false')
            markup = blocks([excerpt], data)
            if excerpt['type'] == 'source':
                excerpt_path = excerpt['path']
                if excerpt_path in seen_paths:
                    markup = markup.replace(f'<span class="path">{esc(excerpt_path)}</span>', '', 1)
                seen_paths.add(excerpt_path)
            excerpts.append(markup)
        # The first source and preceding examples stay inline.
        inline_count = 1 + next((i for i, b in enumerate(diff) if b['type'] == 'source'), 0)
        inline = ''.join(excerpts[:inline_count])
        hidden = excerpts[inline_count:]
        if data.get('layout') == 'paper' and any('open' in b for b in diff):
            chosen = [i for i, b in enumerate(diff) if b.get('open', i < inline_count)]
            inline = ''.join(excerpts[i] for i in chosen)
            hidden = [markup for i, markup in enumerate(excerpts) if i not in chosen]
            if not chosen: raise ValueError('code_walk needs at least one open excerpt')
            sources = [i for i, b in enumerate(diff) if b['type'] == 'source']
            if (len(sources) == 2 and all(i in chosen for i in sources)
                    and {diff[i].get('side', 'head') for i in sources} == {'base', 'head'}):
                pair = f'<div class="paper-excerpt-pair">{"".join(excerpts[i] for i in sources)}</div>'
                inline = ''.join(pair if i == sources[0] else excerpts[i] for i in chosen if i not in sources[1:])
        extra = f'<details><summary>More excerpts</summary>{"".join(hidden)}</details>' if hidden else ''
        rows.append(f'<li><p><span class="code-walk-chip"><code>{esc(path)}</code> <span class="code-walk-tag">{esc(tag)}</span></span> {esc(item["text"])}</p>'
                    f'{inline}{extra}</li>')
    return f'<div class="code-walk">{example}<ol>{"".join(rows)}</ol></div>'


class StepperElements(HTMLParser):
    """Read stable hooks from sanitized markup, without changing the allowlist."""
    def __init__(self, markup):
        super().__init__()
        self.elements = []
        self.definitions = 0
        self.feed(markup)

    def handle_starttag(self, tag, attrs):
        if tag in {'defs', 'marker'}: self.definitions += 1
        if not self.definitions: self.elements.append((tag, dict(attrs)))

    def handle_endtag(self, tag):
        if tag in {'defs', 'marker'}: self.definitions -= 1


def unnumbered(value):
    if isinstance(value, str) and re.match(r'^\s*\d+\.\s+', value):
        raise ValueError('List item text must not start with a number such as "1. "; the renderer supplies numbering')
    return value


def stepper(block, data):
    object_fields(block, 'type title caption visual steps', 'stepper')
    title = text_field(block.get('title'), 'stepper title')
    caption = text_field(block.get('caption'), 'stepper caption')
    visual = block.get('visual')
    if not isinstance(visual, dict) or not isinstance(visual.get('type'), str) or visual['type'] not in {'flow', 'sequence', 'mermaid', 'diagram'}:
        raise ValueError('stepper visual must be mermaid, diagram, flow or sequence')
    kind = visual['type']
    if kind == 'diagram':
        text_field(visual.get('html'), 'stepper diagram html')
        text_field(visual.get('caption'), 'stepper diagram caption')
    targets = []
    edge_ends = {}
    if kind in {'flow', 'sequence'}:
        visual_steps = visual.get('steps')
        if not isinstance(visual_steps, list) or not visual_steps:
            raise ValueError('stepper visual needs steps')
        for field in ('title', 'caption'):
            text_field(visual.get(field), f'stepper visual {field}')
        for item in visual_steps:
            fields = 'label detail icon state' if kind == 'flow' else 'from to message state'
            object_fields(item, fields, 'stepper visual step')
            required = ('label', 'detail') if kind == 'flow' else ('from', 'to', 'message')
            for field in required: unnumbered(text_field(item.get(field), f'stepper visual {field}'))
            states = {'normal', 'active', 'muted', 'blocked'} if kind == 'flow' else {'normal', 'blocked'}
            if not isinstance(item.get('state', 'normal'), str) or item.get('state', 'normal') not in states:
                raise ValueError('Unsupported stepper visual state')
            if 'icon' in item and (not isinstance(item['icon'], str) or item['icon'] not in ICONS):
                raise ValueError('Unsupported stepper visual icon')
        targets = list(range(1, len(visual_steps) + 1))
    elif kind == 'mermaid':
        source = text_field(visual.get('source'), 'stepper Mermaid source').strip()
        if source.startswith('sequenceDiagram'):
            kind = 'mermaid-sequence'
        elif source.startswith(('flowchart', 'graph')):
            kind = 'mermaid-flowchart'
        else:
            raise ValueError('stepper Mermaid must be a sequenceDiagram or flowchart')
    visual_html = blocks([visual], data)
    elements = StepperElements(visual_html).elements
    if kind == 'mermaid-sequence':
        targets = list(range(1, 1 + sum(attrs.get('data-et') == 'message' for _, attrs in elements)))
    elif kind == 'mermaid-flowchart':
        for _, attrs in elements:
            if 'node' in attrs.get('class', '').split():
                match = re.search(r'-flowchart-(.+)-[0-9]+$', attrs.get('id', ''))
                if not match: raise ValueError('stepper Mermaid node has no stable source id')
                targets.append(match[1])
        # Named Mermaid edges omit endpoints from data-id. Read their authored endpoints.
        node = '(?:' + '|'.join(re.escape(key) for key in sorted(targets, key=len, reverse=True)) + ')'
        shape = r'(?:\[[^\n]*?\]|\([^\n]*?\)|\{[^\n]*?\})?'
        named_edge = re.compile(r'(?<![\w-])(' + node + r')\s*' + shape + r'\s+([\w-]+)@[-=.ox<>]+(?:\|[^|]*\|)?\s*(' + node + r')(?![\w-])')
        edge_ends = {match[2]: [match[1], match[3]] for match in named_edge.finditer(source)}
    elif kind == 'diagram':
        targets = [attrs['id'] for _, attrs in elements if attrs.get('id', '').startswith('dg-')]
    if not targets or len(set(targets)) != len(targets):
        raise ValueError('stepper visual needs unique drawable targets (diagram ids must exist outside defs/markers)')
    steps = block.get('steps')
    if not isinstance(steps, list) or not 2 <= len(steps) <= 8:
        raise ValueError('A stepper needs two to eight steps')
    rows = []
    count = len(review_verdict.findings(data['review']['markdown']))
    for index, step in enumerate(steps):
        object_fields(step, 'label text focus finding', 'stepper step')
        label = unnumbered(text_field(step.get('label'), 'stepper label'))
        text = text_field(unnumbered(step.get('text')), 'stepper text', sentences=1)
        focus = step.get('focus', [targets[index]] if index < len(targets) else [])
        if (not isinstance(focus, list) or not focus or
                any(type(key) is not type(targets[0]) or key not in targets for key in focus) or
                len(set(focus)) != len(focus)):
            expected = 'unique 1-based message/step indices in range' if isinstance(targets[0], int) else 'unique ids present in the Mermaid source or diagram markup'
            raise ValueError(f'stepper step {index + 1} focus needs {expected}; available targets: {targets}')
        badge = ''
        if 'finding' in step:
            number = finding_number(step['finding'], count)
            badge = f' <a class="walk-finding" href="#finding-{number}" data-open-finding>⚠ Finding {number}</a>'
        rows.append(f'<li data-focus="{esc(json.dumps(focus))}"><button type="button" class="stepper-note" aria-pressed="false"><strong>{esc(label)}</strong><span>{esc(text)}</span></button>{badge}</li>')
    return (f'<div class="stepper" role="group" aria-label="{esc(title)}" data-visual="{kind}" data-targets="{esc(json.dumps(targets))}" data-edges="{esc(json.dumps(edge_ends))}"><h3>{esc(title)}</h3>'
            f'<div class="stepper-body"><div class="stepper-visual">{visual_html}<p class="caption">{esc(caption)}</p></div>'
            f'<ol class="stepper-texts">{"".join(rows)}</ol></div></div>')


PAPER_KINDS = {'docs', 'config', 'ci', 'deps', 'logic', 'lifecycle', 'data', 'ui', 'refactor', 'api', 'test'}


def source_chip(value):
    object_fields(value, 'label url', 'source')
    label = text_field(value.get('label'), 'source label')
    content = anchor(label, text_field(value['url'], 'source URL')) if 'url' in value else esc(label)
    return f'<span class="paper-source-chip">{content}</span>'


def paper_why(value):
    object_fields(value, 'text sources inferred', 'why')
    text = text_field(value.get('text'), 'why text', sentences=2, words=45)
    if not isinstance(value.get('inferred'), bool): raise ValueError('why inferred must be true or false')
    sources = value.get('sources', [])
    if not isinstance(sources, list) or (not sources and not value['inferred']):
        raise ValueError('why requires at least one source unless inferred')
    chips = ''.join(source_chip(source) for source in sources)
    if value['inferred']: chips += '<span class="paper-source-chip">inferred from the diff</span>'
    return f'<div class="paper-why"><h2>Why this PR exists</h2><p>{esc(text)}</p><div class="paper-source-chips" data-exclude-count>{chips}</div></div>'


def paper_orientation(value):
    object_fields(value, 'open teaser map story terms compare', 'orientation')
    if not isinstance(value.get('open'), bool): raise ValueError('orientation open must be true or false')
    teaser = text_field(value.get('teaser'), 'orientation teaser', words=12)
    prose = [teaser]; content = ''
    if 'map' in value:
        items = value['map']
        if not isinstance(items, list) or not 3 <= len(items) <= 6:
            raise ValueError('orientation map needs three to six items')
        boxes = []; changed = False
        for item in items:
            object_fields(item, 'label name changed', 'orientation map item')
            label = text_field(item.get('label'), 'orientation map label')
            if not isinstance(item.get('changed'), bool): raise ValueError('orientation changed must be true or false')
            changed |= item['changed']; prose.append(label)
            name = ''
            if 'name' in item:
                ident = text_field(item['name'], 'orientation map name')
                if re.search(r'\s', ident): raise ValueError('orientation map name must be an identifier without spaces')
                prose.append(ident); name = f'<code>{esc(ident)}</code>'
            badge = '<small data-exclude-count>this PR</small>' if item['changed'] else ''
            boxes.append(f'<li class="{"changed" if item["changed"] else "unchanged"}"><span>{esc(label)}</span>{name}{badge}</li>')
        if not changed: raise ValueError('orientation map needs at least one changed item')
        content += f'<ol class="paper-system-map" aria-label="You are here">{"".join(boxes)}</ol>'
    if 'story' in value:
        story = text_field(value['story'], 'orientation story', sentences=3); prose.append(story)
        content += f'<p>{esc(story)}</p>'
    if 'map' not in value and 'story' not in value: raise ValueError('orientation requires map or story')
    if 'compare' in value:
        compare = text_field(value['compare'], 'orientation compare', sentences=1); prose.append(compare)
        content += f'<p class="paper-compare">{esc(compare)}</p>'
    terms = value.get('terms', [])
    if not isinstance(terms, list) or len(terms) > 4: raise ValueError('orientation terms needs zero to four terms')
    definitions = []
    for term in terms:
        object_fields(term, 'term meaning', 'orientation term')
        name = text_field(term.get('term'), 'orientation term'); meaning = text_field(term.get('meaning'), 'orientation meaning')
        prose.extend([name, meaning]); definitions.append(f'<dt>{esc(name)}</dt><dd>{esc(meaning)}</dd>')
    if definitions: content += f'<dl>{"".join(definitions)}</dl>'
    text_field(' '.join(prose), 'orientation', words=120)
    opened = ' open' if value['open'] else ''
    return f'<details class="paper-orientation paper-background"{opened}><summary><strong>Background</strong> <span>{esc(teaser)}</span></summary>{content}</details>'


def paper_approach(value):
    object_fields(value, 'text source suggested', 'approach')
    text = text_field(value.get('text'), 'approach text', sentences=2)
    if 'suggested' in value and not isinstance(value['suggested'], bool): raise ValueError('approach suggested must be true or false')
    if value.get('suggested'):
        if 'source' in value: raise ValueError('approach uses source or suggested, not both')
        chip = '<span class="paper-source-chip">our note, not stated by the author</span>'
    else:
        if 'source' not in value: raise ValueError('approach requires source or suggested true')
        chip = source_chip(value['source'])
    return f'<aside class="paper-approach"><h3>Approach</h3><p>{esc(text)}</p><div data-exclude-count>{chip}</div></aside>'


def paper_layers(data):
    text_field(data.get('title'), 'paper title', words=12)
    text_field(data.get('outcome'), 'paper outcome')
    glance = data.get('glance')
    object_fields(glance, 'kind kind_label blast blast_reason findings judgment', 'glance')
    if not isinstance(glance.get('kind'), str) or glance['kind'] not in PAPER_KINDS:
        raise ValueError('Unsupported glance kind')
    if not isinstance(glance.get('blast'), str) or glance['blast'] not in {'contained', 'moderate', 'wide'}:
        raise ValueError('glance blast must be contained, moderate or wide')
    reason = text_field(glance.get('blast_reason'), 'glance blast_reason', words=12)
    label = text_field(glance['kind_label'], 'glance kind_label', words=6) if 'kind_label' in glance else glance['kind']
    findings = review_verdict.findings(data['review']['markdown'])
    # Parse the rendered Markdown, so fenced examples cannot create false findings.
    class Problems(HTMLParser):
        def __init__(self):
            super().__init__(); self.index = -1; self.depth = 0; self.parts = {}; self.in_paragraph = False; self.paragraph = []
        def handle_starttag(self, tag, attrs):
            if tag == 'details':
                self.depth += 1
                if dict(attrs).get('class') == 'review-finding': self.index += 1
            if tag == 'p': self.in_paragraph = True; self.paragraph = []
        def handle_data(self, value):
            if self.in_paragraph: self.paragraph.append(value)
        def handle_endtag(self, tag):
            if tag == 'p':
                text = ''.join(self.paragraph)
                match = re.match(r'The problem in one sentence:\s*(.+)', text, re.I | re.S)
                if match and self.depth and self.index not in self.parts: self.parts[self.index] = match[1].strip()
                self.in_paragraph = False
            if tag == 'details': self.depth -= 1
    problems = Problems(); problems.feed(review_markdown(data['review']['markdown'], data))
    lines = [{'text': problems.parts.get(i) or f['title'], 'finding': f'Finding {i+1}'} for i, f in enumerate(findings)]
    if 'findings' in glance:
        lines = glance['findings']
        if not isinstance(lines, list): raise ValueError('glance findings must be a list')
    rendered = []
    for line in lines:
        object_fields(line, 'text finding', 'glance finding')
        text_field(line.get('text'), 'glance finding text', sentences=1)
        number = finding_number(line.get('finding'), len(findings))
        rendered.append(f'<li><a href="#finding-{number}" data-open-finding>{esc(line["text"])}</a></li>')
    remaining = len(findings) - len({line['finding'].replace('Finding ', '').replace('finding-', '') for line in lines[:2]})
    more = f'<a href="#review-findings">+{remaining} more</a>' if remaining > 0 else ''
    gaps = review_verdict.derive(data['review'])['gaps']
    no_findings = 'No findings' + (f' · {len(gaps)} coverage gap{"" if len(gaps)==1 else "s"}' if gaps else '')
    finding_text = f'<strong>{len(findings)} finding{"" if len(findings)==1 else "s"}</strong><ul>{"".join(rendered[:2])}</ul>{more}' if findings else f'<strong>{no_findings}</strong>'
    judgment = glance.get('judgment', [])
    if not isinstance(judgment, list) or len(judgment) > 3: raise ValueError('glance judgment needs zero to three items')
    questions = []
    for item in judgment:
        object_fields(item, 'text section', 'glance judgment')
        text = esc(text_field(item.get('text'), 'glance judgment text', sentences=1))
        if 'section' in item:
            ident = item['section']
            if not isinstance(ident, str) or ident not in {section['id'] for section in data.get('sections', [])}:
                raise ValueError('judgment section must reference a paper section')
            text = f'<a href="#{esc(ident)}">{text}</a>'
        questions.append(f'<li>{text}</li>')
    judgment_html = f'<aside class="paper-judgment"><h3>Needs your judgment</h3><ul>{"".join(questions)}</ul></aside>' if questions else ''
    result = (f'<section class="paper-glance" aria-label="At a glance"><h2>At a glance</h2><div class="paper-tiles">'
              f'<div><h3>Kind of change</h3><strong>{esc(label)}</strong></div><div><h3>Blast radius</h3><strong>{esc(glance["blast"])}</strong><p>{esc(reason)}</p></div>'
              f'<div class="paper-findings{" paper-findings-long" if rendered else ""}"><h3>Findings</h3>{finding_text}</div></div>{judgment_html}</section>')
    # Derive jump destinations from actual content, including nonstandard section ids.
    targets = {}
    def has_code(value):
        if isinstance(value, dict): return value.get('type') in {'source', 'code_walk'} or any(has_code(v) for v in value.values())
        return isinstance(value, list) and any(has_code(v) for v in value)
    for section in data.get('sections', []):
        if section['id'] in {'change', 'the-change'}: targets.setdefault('The change', section['id'])
        if has_code(section['blocks']): targets.setdefault('Code', section['id'])
        if section['id'] in {'blast', 'blast-radius'} or 'blast radius' in section['title'].lower(): targets.setdefault('Blast radius', section['id'])
    if 'The change' not in targets:
        candidate = next((s for s in data.get('sections', []) if s['id'] not in targets.values()), None)
        if candidate: targets['The change'] = candidate['id']
    links = [f'<a href="#{esc(targets[label])}">{label}</a>' for label in ('The change', 'Code', 'Blast radius') if label in targets]
    links.append(f'<a href="#review-findings">Findings ({len(findings)})</a>')
    separator = '<span aria-hidden="true"> · </span>'
    result += f'<nav class="paper-jumps" aria-label="Jump to">{separator.join(links)}</nav>'
    if 'orientation' in data and 'background' in data: raise ValueError('Use orientation or background, not both')
    if 'orientation' in data: result += paper_orientation(data['orientation'])
    if 'background' in data:
        background = data['background']
        object_fields(background, 'story terms', 'background')
        story = text_field(background.get('story'), 'background story', sentences=3)
        terms = background.get('terms')
        if not isinstance(terms, list) or not 1 <= len(terms) <= 5:
            raise ValueError('background terms needs one to five terms')
        definitions = []; prose = [story]
        for term in terms:
            object_fields(term, 'term meaning', 'background term')
            name = text_field(term.get('term'), 'background term')
            meaning = text_field(term.get('meaning'), 'background meaning')
            prose.extend([name, meaning]); definitions.append(f'<dt>{esc(name)}</dt><dd>{esc(meaning)}</dd>')
        text_field(' '.join(prose), 'background', words=100)
        result += f'<section class="paper-background" data-section="Before you read"><h2>Before you read</h2><p>{esc(story)}</p><dl>{"".join(definitions)}</dl></section>'
    return result


def blocks(items, data):
    output = []
    for block in items:
        kind = block['type']
        if kind == 'paragraph':
            output.append(f'<p>{esc(block["text"])}</p>')
        elif kind == 'list':
            output.append('<ul>' + ''.join(f'<li>{esc(unnumbered(x))}</li>' for x in block['items']) + '</ul>')
        elif kind == 'comparison':
            lanes = []
            for lane in block['lanes']:
                steps = ''.join(f'<li class="step">{esc(unnumbered(x))}</li>' for x in lane['steps'])
                lanes.append(f'<div class="lane"><h3>{esc(lane["title"])}</h3><ol>{steps}</ol></div>')
            output.append(f'<div class="comparison">{"".join(lanes)}</div>')
            if block.get('caption'): output.append(f'<p class="caption">{esc(block["caption"])}</p>')
        elif kind == 'table':
            headers = ''.join(f'<th scope="col">{esc(x)}</th>' for x in block['headers'])
            rows = ''.join('<tr>' + ''.join(f'<td>{esc(x)}</td>' for x in row) + '</tr>' for row in block['rows'])
            output.append(f'<p class="table-hint">Scroll the table horizontally if needed.</p><div class="table-scroll" tabindex="0" role="region" aria-label="Comparison table"><table><thead><tr>{headers}</tr></thead><tbody>{rows}</tbody></table></div>')
        elif kind == 'source':
            output.append(source(block,data))
        elif kind == 'example':
            output.append(f'<figure><div class="source-meta">Illustrative {esc(block.get("language","pseudocode"))} · not an exact source excerpt</div><pre class="example"><code>{esc(block["code"])}</code></pre><figcaption class="caption">{esc(block["caption"])}</figcaption></figure>')
        elif kind == 'details':
            output.append(f'<details><summary>{esc(block["title"])}</summary>{blocks(block["blocks"],data)}</details>')
        elif kind == 'diagram':
            output.append(diagram(block))
        elif kind == 'cases':
            output.append(cases(block, data.get('layout') == 'paper'))
        elif kind == 'flow':
            steps = []
            for number, step in enumerate(block['steps'], 1):
                for field in ('label', 'detail'):
                    if field in step: unnumbered(step[field])
                state = step.get('state', 'normal')
                if state not in {'normal', 'active', 'muted', 'blocked'}:
                    raise ValueError('Unsupported flow state')
                icon = step.get('icon')
                if icon is not None and icon not in ICONS:
                    raise ValueError('Unsupported flow icon')
                graphic = ('<svg viewBox="0 0 32 32" aria-hidden="true" focusable="false">' + ICONS[icon] + '</svg>') if icon else f'<span class="flow-number" aria-hidden="true">{number}</span>'
                steps.append(f'<li class="flow-step {state}"><div class="flow-symbol">{graphic}</div><strong>{esc(step["label"])}</strong><span>{esc(step["detail"])}</span></li>')
            output.append(f'<figure class="flow"><figcaption>{esc(block["title"])}</figcaption><ol>{"".join(steps)}</ol><p class="caption">{esc(block["caption"])}</p></figure>')
        elif kind == 'sequence':
            steps = []
            for step in block['steps']:
                for field in ('from', 'to', 'message'):
                    if field in step: unnumbered(step[field])
                state = step.get('state', 'normal')
                if state not in {'normal', 'blocked'}:
                    raise ValueError('Unsupported sequence state')
                steps.append(f'<li class="sequence-step {state}"><div class="sequence-route"><strong>{esc(step["from"])}</strong><span class="sequence-arrow" aria-hidden="true">→</span><strong>{esc(step["to"])}</strong></div><p>{esc(step["message"])}</p></li>')
            output.append(f'<figure class="sequence"><figcaption>{esc(block["title"])}</figcaption><ol>{"".join(steps)}</ol><p class="caption">{esc(block["caption"])}</p></figure>')
        elif kind == 'scenario':
            frames = block['frames']
            if not 2 <= len(frames) <= 5:
                raise ValueError('A scenario needs two to five meaningful states')
            controls, panels = [], []
            for i, frame in enumerate(frames):
                if any(b.get('type') not in {'flow', 'sequence', 'paragraph'} for b in frame['blocks']):
                    raise ValueError('Scenario states support flow, sequence and paragraph blocks')
                controls.append(f'<button type="button" data-frame="{i}" aria-pressed="false">{esc(frame["label"])}</button>')
                panels.append(f'<div class="scenario-frame" data-frame="{i}" role="region" aria-label="{esc(frame["label"])}"><h4 class="scenario-frame-label">{esc(frame["label"])}</h4>{blocks(frame["blocks"], data)}</div>')
            output.append(f'<div class="scenario" role="group" aria-label="{esc(block["title"])}"><h3>{esc(block["title"])}</h3><div class="scenario-controls" hidden>{"".join(controls)}</div>{"".join(panels)}<p class="caption">{esc(block["caption"])}</p></div>')
        elif kind == 'mermaid':
            output.append(mermaid(block, data))
        elif kind == 'card':
            output.append(card(block))
        elif kind == 'callouts':
            output.append(callouts(block))
        elif kind == 'compare':
            output.append(compare(block, data))
        elif kind == 'pair':
            output.append(pair(block, data))
        elif kind == 'code_walk':
            output.append(code_walk(block, data))
        elif kind == 'stepper':
            output.append(stepper(block, data))
        else: raise ValueError(f'Unsupported block type: {kind}')
    return ''.join(output)

UPDATE_STATUSES = {'resolved': 'Resolved', 'still-open': 'Still open', 'changed': 'Changed', 'new': 'New', 'withdrawn': 'Withdrawn'}
SHA = re.compile('[a-f0-9]{40}')

def update_record(data):
    """Validate the optional record of what changed since a previous review."""
    update = data.get('update')
    if update is None:
        return None
    if not isinstance(update, dict) or update.get('scope') not in {'update', 'full'}:
        raise ValueError('An update record needs scope update or full')
    previous = update.get('previous')
    if not isinstance(previous, dict) or not all(isinstance(previous.get(k), str) and SHA.fullmatch(previous[k]) for k in ('base', 'head')):
        raise ValueError('An update record needs the previous review base and head SHAs')
    if not isinstance(previous.get('run_id', ''), str) or not re.fullmatch(r'[A-Za-z0-9._-]{0,128}', previous.get('run_id', '')):
        raise ValueError('Previous run ID is invalid')
    if update['scope'] == 'update' and (previous['head'] == data['head'] or previous['base'] != data['base']):
        raise ValueError('An update must keep the previous comparison base and cover a newer head; run a full review otherwise')
    if not isinstance(update.get('summary'), str) or not update['summary'].strip():
        raise ValueError('Say in the update summary what changed since the previous review')
    findings = update.get('findings', [])
    if not isinstance(findings, list):
        raise ValueError('Update findings must be a list')
    for finding in findings:
        if not isinstance(finding, dict) or not isinstance(finding.get('title'), str) or not finding['title'].strip():
            raise ValueError('Each update finding needs a title')
        if finding.get('status') not in UPDATE_STATUSES:
            raise ValueError('Update finding status must be resolved, still-open, changed, new or withdrawn')
        if not isinstance(finding.get('note', ''), str):
            raise ValueError('Update finding notes must be text')
    return update

def previous_verdict(update):
    """The previous run's verdict, re-derived from its saved input by the same rules."""
    run_id = (update or {}).get('previous', {}).get('run_id')
    if not run_id: return None
    try:
        previous = json.loads((tracker.run_dir(run_id) / 'input.json').read_text())
        result = review_verdict.derive(previous['review'])
    except (tracker.TrackerError, OSError, ValueError, KeyError, TypeError):
        return None
    return {'tone': result['tone'], 'headline': result['headline'], 'head': update['previous']['head']}

def update_section(update, data):
    scope = 'Updated review' if update['scope'] == 'update' else 'Full re-review'
    previous = update['previous']
    summary = review_markdown(update['summary'], data)
    if re.search(r'<details\b|class="review-comment"', summary):
        raise ValueError('Keep the update summary visible and copyable comments in findings')
    rows = ''.join(f'<tr><td><span class="update-status update-{esc(f["status"])}">{esc(UPDATE_STATUSES[f["status"]])}</span></td>'
                   f'<td>{esc(f["title"])}</td><td>{esc(f.get("note", ""))}</td></tr>' for f in update.get('findings', []))
    table = (f'<div class="table-scroll" tabindex="0" role="region" aria-label="Findings since the last review"><table class="update-findings">'
             f'<thead><tr><th scope="col">Status</th><th scope="col">Finding</th><th scope="col">What changed</th></tr></thead><tbody>{rows}</tbody></table></div>') if rows else ''
    return (f'<section id="since-last-review" data-section="Since the last review"><h2>Since the last review</h2>'
            f'<p class="update-scope">{scope} · previous review of <code>{esc(previous["head"][:12])}</code> → this review of <code>{esc(data["head"][:12])}</code></p>'
            f'{summary}{table}</section>')

def render(data):
    for side in ('base','head'):
        if not re.fullmatch('[a-f0-9]{40}',data[side]) and not (side=='head' and data[side]=='working-tree'):
            raise ValueError('Use full commit SHAs, or head=working-tree')
    if data.get('repo_url') and not re.fullmatch(r'https://github\.com/[\w.-]+/[\w.-]+',data['repo_url']):
        raise ValueError('repo_url must identify a verified GitHub repository')
    if data.get('pr_url') and not re.fullmatch(re.escape(data.get('repo_url','')) + r'/pull/[1-9]\d*',data['pr_url']):
        raise ValueError('PR URL must belong to the verified repository')
    layout=data.get('layout','classic')
    if layout not in {'classic','walk','paper'}: raise ValueError('layout must be classic, walk or paper')
    preflight_blobs(data)
    data={**data,'_mermaid':review_mermaid.render_all(data)}
    mode=data.get('mode','Brief · Standard')
    if mode not in {'Brief · Small','Brief · Standard','Deep'}: raise ValueError('Unknown mode')
    if not data.get('evidence'): raise ValueError('Keep a checked evidence record in the input')
    review = data.get('review')
    if not isinstance(review, dict) or not review.get('markdown', '').strip():
        raise ValueError('A combined report requires review Markdown')
    if review.get('base') != data['base'] or review.get('head') != data['head']:
        raise ValueError('Explanation and review must use the same pinned revisions')
    errors, _ = validate(review['markdown'])
    if errors:
        raise ValueError('; '.join(errors))
    assessment = ''
    if 'assessment' in review:
        text = review['assessment']
        if not isinstance(text, str) or not text.strip():
            raise ValueError('Assessment must be non-empty Markdown')
        assessment_html = review_markdown(text, data)
        if re.search(r'<details\b|class="(?:review-comment|scenario|flow|sequence|diagram|cases)"', assessment_html):
            raise ValueError('Keep assessment visible and copyable comments in findings')
        assessment = ('<div class="review-assessment" id="review-assessment" '
                      'aria-labelledby="assessment-title"><h2 id="assessment-title">Current assessment</h2>'
                      + assessment_html
                      + '<a class="findings-link" href="#review-findings">Jump to findings and checks</a></div>')
    update=update_record(data)
    if 'verdict' in review:
        if 'assessment' not in review: raise ValueError('A verdict needs review.assessment')
        resolved=[f['title'] for f in (update or {}).get('findings', []) if f['status']=='resolved']
        assessment = review_verdict.render(review, assessment_html, review_inline(data), esc, data['head'],
                                           previous_verdict(update), resolved, paper=layout=='paper')
    sections=[]; nav=[]; seen=set()
    # A walk reads the change first; the update record follows the findings there.
    if update and layout=='classic':
        sections.append(update_section(update,data));nav.append('<a href="#since-last-review">Since the last review</a>')
    for section in data.get('sections',[]):
        ident=section['id']
        if not re.fullmatch(r'[a-z][a-z0-9-]*',ident) or re.fullmatch(r'finding-\d+',ident) or ident in seen or ident in {'self-check','references','provenance','theme','review-findings','verification','review-assessment','assessment-title','since-last-review'}: raise ValueError('Use unique section IDs')
        seen.add(ident);nav.append(f'<a href="#{ident}">{esc(section.get("tab") or section["title"])}</a>')
        verified=section.get('verified_at',data['head'])
        if verified!=data['head'] and (not isinstance(verified,str) or not SHA.fullmatch(verified) or not update):
            raise ValueError('A section verified at an older head needs a full SHA and an update record')
        carried=f'<p class="carried-note">Carried from the review of <code>{esc(verified[:12])}</code>, not re-derived in this update. Source excerpts show this head.</p>' if verified!=data['head'] else ''
        if layout in {'walk','paper'}:
            if layout=='paper':
                text_field(section.get('claim'), 'paper section claim')
                if 'lede' in section: text_field(section['lede'], 'paper section lede')
            lede=f'<p class="walk-lede">{esc(section["lede"])}</p>' if section.get('lede') else ''
            head=f'<div class="walk-scene-head"><h2>{esc(section.get("claim") or section["title"])}</h2>{lede}</div>'
        else:
            head=f'<h2>{esc(section["title"])}</h2>'
        body = blocks(section['blocks'], data)
        if layout == 'paper' and 'approach' in section:
            split = next((i for i, block in enumerate(section['blocks']) if block['type'] not in {'paragraph', 'list'}), len(section['blocks']))
            body = blocks(section['blocks'][:split], data) + paper_approach(section['approach']) + blocks(section['blocks'][split:], data)
        sections.append(f'<section id="{ident}" data-section="{esc(section["title"])}">{head}{carried}{body}</section>')
    # Number findings in render order so the verdict's links can open them.
    numbers=itertools.count(1)
    findings_html=re.sub(re.escape(FINDING_OPEN), lambda _: f'<details class="review-finding" id="finding-{next(numbers)}">', review_markdown(review['markdown'], data))
    sections.append('<section id="review-findings" data-section="Review findings"><h2>Review findings</h2>' + findings_html + '</section>')
    nav.append('<a href="#review-findings">Review findings</a>')
    if update and layout in {'walk','paper'}:
        sections.append(update_section(update,data));nav.append('<a href="#since-last-review">Since the last review</a>')
    quiz=[]; questions=data.get('questions',[])
    if len(questions) > (5 if mode=='Deep' else 3): raise ValueError('Too many self-check questions')
    for i,q in enumerate(questions):
        opts=q['options']; correct=q['answer']
        if not 2<=len(opts)<=4 or not isinstance(correct,int) or not 0<=correct<len(opts):raise ValueError('Questions need 2–4 choices and one valid answer index')
        target=i % len(opts); order=list(range(len(opts)));order[correct],order[target]=order[target],order[correct]
        buttons=''.join(f'<button type="button">{chr(65+j)}. {esc(opts[k])}</button>' for j,k in enumerate(order))
        quiz.append(f'<div class="question" data-answer="{target}"><h3>{i+1}. {esc(q["question"])}</h3><div class="options">{buttons}</div><p class="feedback" role="status" aria-live="polite" data-exclude-count="true"></p><p class="quiz-explanation" hidden>{esc(q["explanation"])}</p></div>')
    if quiz:
        sections.append(f'<section id="self-check" data-section="Self-check"><details id="quiz"><summary>Check your understanding · {len(quiz)} question{"s" if len(quiz)!=1 else ""}</summary>{"".join(quiz)}<button class="reset" id="reset-quiz" type="button">Reset answers</button></details></section>')
        nav.append('<a href="#self-check">Self-check</a>')
    if data.get('verification'):
        sections.append('<section id="verification" data-section="Verification"><details><summary>Verification details and coverage</summary>' + review_markdown(data['verification'], data) + '</details></section>')
        nav.append('<a href="#verification">Verification</a>')
    refs=''.join(f'<li>{anchor(x["label"],x["url"])}</li>' for x in data.get('references',[]))
    if refs:sections.append(f'<details class="references" id="references"><summary>Sources and related review</summary><ul>{refs}</ul></details>')
    provenance=''.join(f'<dt>{esc(k)}</dt><dd>{esc(v)}</dd>' for k,v in [('Repository',data.get('repo_url',data['repository'])),('Comparison base',data['base']),('Reviewed head',data['head']),*([('Previous review',update['previous']['head']+(' · run '+update['previous']['run_id'] if update['previous'].get('run_id') else ''))] if update else []),('Context',data.get('context','Pinned source comparison'))])
    pr=anchor('Open pull request',data['pr_url']) if data.get('pr_url') else ''
    overview=f'<h1>{esc(data["title"])}</h1><p class="outcome">{esc(data["outcome"])}</p>{assessment}<div class="actions"><span class="meta">{esc(data["stack"])} · approximately READING_MINUTES min read</span><span class="pr-link">{pr}</span></div><details class="provenance" id="provenance"><summary>Reviewed revision and context</summary><dl>{provenance}</dl></details>'
    topbar='<div class="topbar"><span class="badge">Review notes</span><button id="theme" type="button">Theme: System</button></div>'
    if layout=='walk':
        # Only advertise the inspector when a non-stepper Mermaid has actors.
        inspector = re.sub(r'<div class="stepper".*?<ol class="stepper-texts">.*?</ol></div></div>', '', ''.join(sections), flags=re.S)
        inspect_hint = ' Click a diagram participant to inspect it.' if 'data-et="participant"' in inspector else ''
        content=(f'<main class="walk-page"><article class="walk"><header data-section="Overview">{topbar}{walk_heading(data)}{overview}</header>'
                 f'<div class="walk-body"><nav class="walk-rail" aria-label="Scenes"><p class="walk-eyebrow">Scenes</p><ol>{"".join(f"<li>{a}</li>" for a in nav)}</ol>'
                 f'<p class="walk-rail-note">1–9 or ← → switch scenes.{inspect_hint}</p></nav>'
                 f'<div class="walk-scenes">{"".join(sections)}</div></div></article></main>')
    elif layout=='paper':
        # Findings end the article; auxiliary material stays in a collapsed tail.
        end = next(i for i, item in enumerate(sections) if item.startswith('<section id="review-findings"')) + 1
        tail = ''.join(sections[end:])
        layers = paper_layers(data)
        why = paper_why(data['why']) if 'why' in data else ''
        overview = (f'<h1>{esc(data["title"])}</h1>{why}{assessment}<div class="actions"><span class="pr-link">{pr}</span></div>'
                    f'<p class="outcome">{esc(data["outcome"])}</p>')
        content = (f'<main class="paper-page" data-kind="{esc(data["glance"]["kind"])}"><header data-section="Overview">{topbar}{walk_heading(data)}{overview}</header>'
                   f'{layers}<div class="paper-sections">{"".join(sections[:end])}</div>'
                   f'<details class="paper-tail"><summary>Questions, verification and sources</summary>{tail}'
                   f'<details class="provenance" id="provenance"><summary>Reviewed revision and context</summary><dl>{provenance}</dl></details></details></main>')
    else:
        content=f'<main><header data-section="Overview">{topbar}{overview}</header><nav aria-label="On this page">{"".join(nav)}</nav>{"".join(sections)}</main>'
    words=OverviewWords().count(content)
    content=content.replace('READING_MINUTES min read',f'{max(1,math.ceil(words/180))} min overview · findings and evidence extra')
    css=(ASSETS/'review.css').read_text();js=(ASSETS/'review.js').read_text();csp=CSP
    js, paper_js = js.split('\n// Paper responsive diagrams', 1)
    if 'class="stepper"' not in content and 'class="code-walk"' not in content:
        css=css.split('\n/* Layered code walk')[0]
    if 'class="stepper"' not in content:
        js=js.split('\n// Reader-advanced visual steps')[0]
    css+=(ASSETS/'review-walk.css').read_text()
    walk_js=(ASSETS/'review-walk.js').read_text()
    label_lines, wrapped_messages = 0, False
    for _, attrs in StepperElements(content).elements:
        if 'messageText' in attrs.get('class', '').split(): label_lines += 1
        if attrs.get('data-et') == 'message':
            wrapped_messages |= label_lines > 1
            label_lines = 0
    # Keep legacy report bytes stable unless a wrapped label needs the fix.
    if wrapped_messages:
        walk_js = walk_js.replace("const t=line.previousElementSibling;if(t?.classList.contains('messageText'))t.classList.add('dim');",
                                  "for(let t=line.previousElementSibling;t&&!t.matches('[data-et=message]');t=t.previousElementSibling)if(t.classList.contains('messageText'))t.classList.add('dim');")
    if 'class="stepper"' in content:
        # The stepper owns Mermaid focus; skip the older participant click inspector.
        walk_js=walk_js.replace("for(const figure of document.querySelectorAll('.mermaid-figure')){", "for(const figure of document.querySelectorAll('.mermaid-figure')){if(figure.closest('.stepper'))continue;")
    js+=walk_js
    if layout=='paper':
        css+=(ASSETS/'review-paper.css').read_text()
        js+='\n// Paper responsive diagrams'+paper_js
    if layout in {'walk','paper'}:
        css=walk_fonts()+css;csp=CSP.replace("font-src 'none'","font-src data:")
    return f'<!doctype html><html lang="en" data-mode="{esc(mode)}" data-layout="{layout}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="{esc(csp)}"><title>{esc(data["title"])}</title><style>{css}</style></head><body>{content}<script>{js}</script></body></html>'

# Fraunces and IBM Plex (OFL, assets/fonts/LICENSES.txt), subset to the characters reports use.
WALK_FONTS = (('Fraunces', 600, 'fraunces-600.woff2'), ('IBM Plex Sans', 400, 'ibm-plex-sans-400.woff2'),
              ('IBM Plex Sans', 600, 'ibm-plex-sans-600.woff2'), ('IBM Plex Mono', 400, 'ibm-plex-mono-400.woff2'))

def walk_fonts():
    faces = []
    for family, weight, name in WALK_FONTS:
        font = base64.b64encode((ASSETS / 'fonts' / name).read_bytes()).decode()
        faces.append(f'@font-face{{font-family:"{family}";font-weight:{weight};font-display:swap;src:url(data:font/woff2;base64,{font}) format("woff2")}}')
    return ''.join(faces)

def walk_heading(data):
    repo = ''
    if data.get('pr_url'):
        parts = urlsplit(data['pr_url']).path.strip('/').split('/')
        repo = f'{parts[0]}/{parts[1]} #{parts[3]}'
    stats, pills = data.get('stats') or {}, ''
    if isinstance(stats.get('additions'), int): pills += f'<span class="walk-pill tone-add">+{stats["additions"]:,}</span>'
    if isinstance(stats.get('deletions'), int): pills += f'<span class="walk-pill tone-del">−{stats["deletions"]:,}</span>'
    if isinstance(stats.get('files'), int): pills += f'<span class="walk-pill">{stats["files"]} file{"" if stats["files"] == 1 else "s"}</span>'
    label = ' · '.join(x for x in (repo, data.get('stack', '')) if x) or 'Review'
    return f'<div class="walk-head-row"><p class="walk-eyebrow">{esc(label)}</p><div class="walk-pills">{pills}</div></div>'

def main():
    parser=argparse.ArgumentParser();parser.add_argument('input',type=Path);parser.add_argument('output',type=Path);args=parser.parse_args()
    data=json.loads(args.input.read_text());output=render(data);args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(output)
    # The dashboard card reads this sidecar; it never re-derives from the model's input.
    sidecar=args.output.with_name(VERDICT_SIDECAR)
    if 'verdict' in data['review']:
        sidecar.write_text(json.dumps(review_verdict.summary(review_verdict.derive(data['review']))|{'head':data['head']}))
    elif sidecar.exists(): sidecar.unlink()
    print(args.output.resolve())

if __name__=='__main__':main()

"""Advisory approval verdict shown at the top of a review report.

The model records what was checked and why; the colour, headline and confidence
come only from these rules, so a green verdict can never sit above an open P0/P1
and confidence reflects coverage, not the model's own certainty.
"""
from __future__ import annotations
import re

FINDING = '<details class="review-finding">'
FENCE = re.compile(r'^\s*(`{3,}|~{3,})')
SEVERITIES = {'p0': 'P0', 'p1': 'P1', 'p2': 'P2', 'p3': 'P3', 'optional': 'optional',
              'needs confirmation': 'needs-confirmation'}
LABELS = {'P0': 'P0', 'P1': 'P1', 'P2': 'P2', 'P3': 'P3', 'optional': 'Optional',
          'needs-confirmation': 'Needs confirmation'}
TESTS = ('pass', 'fail', 'not-run')
RUNTIME = ('validated', 'not-needed', 'not-run')
KINDS = ('ready', 'nits', 'question', 'changes', 'blocked', 'partial')
TONES = ('good', 'warn', 'bad', 'muted')
SHORT = {'ready': 'Ready', 'nits': 'Approvable', 'question': 'Question open', 'changes': 'Fix first',
         'blocked': 'Changes needed', 'partial': 'Incomplete'}
CONSIDER = {'ready': 'Before approving, consider', 'nits': 'Before approving, consider',
            'question': 'Settle before approving', 'changes': 'Fix before approving',
            'blocked': 'Fix before approving', 'partial': 'Still to review'}
ICONS = {'good': '<path d="M5 12.5l4.5 4.5L19 7.5"/>', 'warn': '<path d="M12 7.5v6"/><path d="M12 17h.01"/>',
         'bad': '<path d="M7.5 7.5l9 9M16.5 7.5l-9 9"/>', 'muted': '<path d="M7 12h10"/>'}


def findings(markdown):
    """Severity and title of each finding, in the order the report renders them."""
    result, fence, pending = [], None, False
    for line in markdown.splitlines():
        stripped = line.strip()
        match = FENCE.match(stripped)
        if match:
            token = match[1]
            if fence is None: fence = token
            elif token[0] == fence[0] and len(token) >= len(fence): fence = None
            continue
        if fence:
            continue
        if stripped == FINDING:
            pending = True
        elif pending and stripped:
            pending = False
            summary = re.fullmatch(r'<summary>(.*?)</summary>', stripped)
            if summary:
                head, _, title = summary[1].partition('·')
                severity = SEVERITIES.get(head.strip().lower().replace('-', ' '))
                if not severity:
                    raise ValueError('Start each finding summary with P0–P3, Optional or Needs confirmation for the verdict')
                result.append({'severity': severity, 'title': title.strip()})
    return result


def validate(value):
    if not isinstance(value, dict):
        raise ValueError('review.verdict must be an object')
    for key in ('complete', 'traced'):
        if not isinstance(value.get(key), bool):
            raise ValueError(f'review.verdict.{key} must be true or false')
    if value.get('tests') not in TESTS:
        raise ValueError('review.verdict.tests must be pass, fail or not-run')
    if value.get('runtime') not in RUNTIME:
        raise ValueError('review.verdict.runtime must be validated, not-needed or not-run')
    for key, required in (('why', True), ('checked', True), ('unreviewed', False)):
        items = value.get(key, [])
        if (required and not items) or not isinstance(items, list) or not all(isinstance(i, str) and i.strip() for i in items):
            raise ValueError(f'review.verdict.{key} must be a {"non-empty " if required else ""}list of text')
    note = value.get('tests_note', '')
    if not isinstance(note, str) or len(note.split()) > 15:
        raise ValueError('review.verdict.tests_note must be text of at most 15 words')
    if not isinstance(value.get('runtime_note', ''), str):
        raise ValueError('review.verdict.runtime_note must be text')
    return value


def _count(items, kinds):
    return sum(item['severity'] in kinds for item in items)


def _plural(n, word):
    return f'{n} {word}{"" if n == 1 else "s"}'


def _kind(items, complete):
    if not complete: return 'partial'
    if _count(items, ('P0', 'P1')): return 'blocked'
    if _count(items, ('P2',)): return 'changes'
    if _count(items, ('needs-confirmation',)): return 'question'
    if _count(items, ('P3', 'optional')): return 'nits'
    return 'ready'


def _headline(kind, items):
    questions = _count(items, ('needs-confirmation',))
    return {
        'partial': 'Not fully reviewed',
        'blocked': 'Changes needed · ' + _plural(_count(items, ('P0', 'P1')), 'serious issue'),
        'changes': 'Worth fixing first · ' + _plural(_count(items, ('P2',)), 'issue'),
        'question': 'Settle ' + ('one question' if questions == 1 else f'{questions} questions') + ' first',
        'nits': 'Approvable · ' + _plural(_count(items, ('P3', 'optional')), 'small suggestion'),
        'ready': 'Ready to approve',
    }[kind]


def gaps(verdict):
    result = []
    if not verdict['traced']: result.append('Changed paths were read but not traced end to end.')
    if verdict['tests'] == 'not-run': result.append('The tests were not run at this revision.' + (' ' + verdict['tests_note'].strip() if verdict.get('tests_note', '').strip() else ''))
    if verdict['runtime'] == 'not-run':
        result.append(verdict.get('runtime_note') or 'The changed behavior was not exercised at runtime.')
    result += ['Not reviewed: ' + area.strip().rstrip('.') + '.' for area in verdict.get('unreviewed', [])]
    if verdict['tests'] == 'fail': result.insert(0, 'Checks failed' + (': ' + verdict['tests_note'].strip() if verdict.get('tests_note', '').strip() else '.'))
    return result


def derive(review):
    """Verdict for a review input; `review.verdict` absent means severity-only (legacy reports)."""
    items = findings(review.get('markdown', ''))
    verdict = review.get('verdict')
    if verdict is None:
        kind = _kind(items, True)
        return {'kind': kind, 'tone': 'bad' if kind == 'blocked' else 'warn' if kind in ('changes', 'question') else 'good',
                'headline': _headline(kind, items), 'confidence': None, 'gaps': [], 'findings': items}
    validate(verdict)
    missing = gaps(verdict)
    # Failing tests always mean low; otherwise one or two gaps are medium, three or more low.
    confidence = 'low' if verdict['tests'] == 'fail' or len(missing) >= 3 else 'medium' if missing else 'high'
    kind = _kind(items, verdict['complete'])
    unsure = kind in ('ready', 'nits') and confidence == 'low'
    tone = ('muted' if kind == 'partial' else 'bad' if kind == 'blocked'
            else 'warn' if kind in ('changes', 'question') or unsure else 'good')
    headline = 'Probably approvable · check the gaps yourself' if unsure else _headline(kind, items)
    return {'kind': kind, 'tone': tone, 'headline': headline,
            'confidence': None if kind == 'partial' else confidence, 'gaps': missing, 'findings': items}


def summary(result):
    """Compact form for the dashboard card."""
    return {k: result[k] for k in ('kind', 'tone', 'headline', 'confidence')} | {'short': SHORT[result['kind']]}


def icon(tone):
    return f'<svg class="verdict-svg" viewBox="0 0 24 24" aria-hidden="true">{ICONS[tone]}</svg>'


def render(review, assessment_html, inline, esc, head, previous=None, resolved=(), *, paper=False):
    """Verdict card HTML: one collapsed row, everything else inside it.

    Finding links target the ids render_review assigns.
    """
    result = derive(review)
    verdict = review['verdict']
    consider = [f'<li><a href="#finding-{i}" data-open-finding>{esc(LABELS[f["severity"]])} · {inline(f["title"])}</a></li>'
                for i, f in enumerate(result['findings'], 1)]
    consider += [f'<li>{inline(gap)}</li>' for gap in result['gaps']]
    meter = ''
    if result['confidence']:
        on = {'high': 3, 'medium': 2, 'low': 1}[result['confidence']]
        bars = ''.join(f'<i class="{"on" if i <= on else ""}"></i>' for i in (1, 2, 3))
        meter = f'<span class="confidence"><span class="bars" aria-hidden="true">{bars}</span>{result["confidence"].capitalize()} confidence</span>'
    revision = 'working tree' if head == 'working-tree' else f'<code>{esc(head[:12])}</code>'
    meta = [revision] + ([f'{len(consider)} thing{"" if len(consider) == 1 else "s"} to consider'] if consider else [])
    if paper:
        meta = [revision]
        if result['findings']: meta.append(_plural(len(result['findings']), 'finding'))
        if result['gaps']: meta.append(_plural(len(result['gaps']), 'coverage gap'))
    change = ''
    if previous:
        chip = f'<span class="verdict-chip tone-{previous["tone"]}">{icon(previous["tone"])}{esc(previous["headline"])}</span>'
        if previous['headline'] != result['headline']:
            # Plain text, not a coloured chip, so the earlier verdict never reads as current.
            if resolved:
                meta.append(f'✓ {len(resolved)} earlier issue{"" if len(resolved) == 1 else "s"} fixed')
            else:
                meta.append(f'earlier review: {esc(previous["headline"])}')
        where = 'on the same commit' if previous['head'] == head else f'at <code>{esc(previous["head"][:12])}</code>'
        fixed = f' Fixed since: {"; ".join(esc(t) for t in resolved)}.' if resolved else ''
        change = f'<p class="verdict-change">Previous review {where}: {chip}.{fixed}</p>'
    listing = f'<ul>{"".join(consider)}</ul>' if consider else '<p class="verdict-muted">Nothing outstanding.</p>'
    why = ''.join(f'<li>{inline(item)}</li>' for item in verdict['why'])
    tests_note = f'<p class="verdict-tests">Tests passed · {esc(verdict["tests_note"].strip())}</p>' if verdict['tests'] == 'pass' and verdict.get('tests_note', '').strip() else ''
    checked = ''.join(f'<li>{inline(item)}</li>' for item in verdict['checked'])
    return (f'<details class="verdict tone-{result["tone"]}" id="review-assessment">'
            f'<summary class="verdict-head"><span class="verdict-icon">{icon(result["tone"])}</span>'
            f'<span class="verdict-text"><span class="verdict-eyebrow">AI review verdict</span>'
            f'<h2 id="assessment-title">{esc(result["headline"])}</h2>'
            f'<span class="verdict-meta">{" · ".join(meta)}</span></span>{meter}'
            f'<span class="verdict-toggle" aria-hidden="true"></span></summary>'
            f'<div class="verdict-body"><div class="verdict-assessment">{assessment_html}</div>{change}'
            f'<h3>Why</h3><ul>{why}</ul><h3>{CONSIDER[result["kind"]]}</h3>{listing}'
            f'<h3>What was checked</h3>{tests_note}<ul class="verdict-checked">{checked}</ul>'
            f'<p class="verdict-note">Advisory, derived from the findings and checks. The approval decision is yours. '
            f'<a class="findings-link" href="#review-findings">Jump to findings and checks</a></p></div></details>')

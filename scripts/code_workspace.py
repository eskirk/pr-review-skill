"""Workspace application service shared by HTTP handlers and tests."""
import html
import re
from urllib.parse import unquote, urlsplit
import dashboard_runtime as runtime
import pr_dashboard as dashboard
import pr_review_tracker as tracker
import workspace_github as github
import workspace_store as store
import workspace_chat as chat
import workspace_comments as comments
import ai_settings
import review_continuation
import review_markdown as review_notes
from render_review import comment_footer


FINDING = '<details class="review-finding">'
COMMENT_START = '<!-- review-comment:start -->'
COMMENT_END = '<!-- review-comment:end -->'
FINDING_ID = re.compile(r'^finding-([1-9][0-9]*)$')
MAX_FINDING = 1000
SHA = re.compile(r'^[0-9a-f]{40}$')
URL_RE = re.compile(r'https://github\.com/[^\s<>"\']+')


def _finding_blocks(markdown):
    lines = str(markdown or '').replace('\r\n', '\n').split('\n')
    result = []
    fence = None
    for index, line in enumerate(lines):
        match = re.match(r'^\s*(`{3,}|~{3,})(.*)$', line)
        if match:
            token = match.group(1)
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence) and not match.group(2).strip():
                fence = None
            continue
        if fence is None and line.strip() == FINDING:
            end = review_notes.find_close(lines, index + 1, '</details>')
            if end is not None:
                result.append(lines[index:end + 1])
    return result


def _comment_body(lines):
    fence = None
    start = None
    for index, line in enumerate(lines):
        match = re.match(r'^\s*(`{3,}|~{3,})(.*)$', line)
        if match:
            token = match.group(1)
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence) and not match.group(2).strip():
                fence = None
            continue
        if fence is not None:
            continue
        if line.strip() == COMMENT_START:
            if start is not None:
                raise ValueError('A finding has nested comment drafts.')
            start = index + 1
        elif line.strip() == COMMENT_END and start is not None:
            return '\n'.join(lines[start:index]).strip()
    return None


def _finding_title(lines):
    for line in lines:
        match = re.fullmatch(r'\s*<summary>(.*?)</summary>\s*', line)
        if match:
            return html.unescape(re.sub(r'<[^>]+>', '', match.group(1))).strip()
    return ''


def _urls(text):
    for value in URL_RE.findall(str(text or '')):
        yield value.rstrip('.,;:!?`)]')


def _report_target(markdown, comparison):
    repository = comparison['repository'].split('/')
    if len(repository) != 2:
        raise ValueError('Invalid repository identity.')
    owner, name = repository
    pull_prefix = f'/{owner}/{name}/pull/{comparison["number"]}'
    for value in _urls(markdown):
        parsed = urlsplit(value)
        if parsed.path == pull_prefix:
            match = re.fullmatch(r'(?:discussion_r|pullrequestreviewcomment-)([1-9][0-9]*)', parsed.fragment)
            if match:
                return {'mode': 'reply', 'in_reply_to': int(match.group(1)),
                        'url': value, 'label': 'Reply to the existing GitHub review thread'}
    for value in _urls(markdown):
        parsed = urlsplit(value)
        parts = parsed.path.strip('/').split('/')
        if len(parts) < 5 or parts[:3] != [owner, name, 'blob'] or not SHA.fullmatch(parts[3]):
            continue
        line_match = re.fullmatch(r'L([1-9][0-9]*)(?:-L([1-9][0-9]*))?', parsed.fragment)
        if not line_match or parts[3] not in (comparison['base'], comparison['head']):
            continue
        path = unquote('/'.join(parts[4:]))
        if not path or path.startswith('/') or any(item in ('.', '..') for item in path.split('/')):
            continue
        start, end = int(line_match.group(1)), int(line_match.group(2) or line_match.group(1))
        if start > end:
            continue
        side = 'LEFT' if parts[3] == comparison['base'] else 'RIGHT'
        return {'mode': 'inline', 'path': path, 'line': end,
                'start_line': start if start != end else None, 'side': side,
                'commit_id': comparison['head'], 'url': value,
                'label': f'New inline review thread · {path}:{start}' + (f'–{end}' if start != end else '')}
    return {'mode': 'conversation', 'label': 'New comment in the pull request conversation'}


def _review_markdown(directory, input_data):
    source = directory / 'review.md'
    try:
        if source.is_file():
            return source.read_text()
    except OSError as error:
        raise ValueError('The saved review finding is unavailable.') from error
    review = input_data.get('review') if isinstance(input_data, dict) else None
    markdown = review.get('markdown') if isinstance(review, dict) else None
    if not isinstance(markdown, str):
        raise ValueError('The saved review finding is unavailable.')
    return markdown


def _finding_artifact(url, head, version, finding_id):
    match = FINDING_ID.fullmatch(str(finding_id or ''))
    if not match:
        raise ValueError('Invalid review finding.')
    info = review(url, head)
    artifact = info.get('artifact') or {}
    if not artifact or artifact.get('version') != version:
        raise ValueError('This review finding is no longer available. Reload the AI review tab.')
    report_head = artifact.get('head_sha')
    if not isinstance(report_head, str) or not SHA.fullmatch(report_head):
        raise ValueError('This review finding has no pinned revision.')
    run_id = artifact.get('run_id')
    if not isinstance(run_id, str) or not run_id:
        raise ValueError('This review finding has no saved source.')
    directory = tracker.run_dir(run_id)
    input_data = tracker.read_json(directory / 'input.json', required=False)
    markdown = _review_markdown(directory, input_data)
    blocks = _finding_blocks(markdown)
    index = int(match.group(1)) - 1
    if index < 0 or index >= MAX_FINDING or index >= len(blocks):
        raise ValueError('This review finding is no longer available. Reload the AI review tab.')
    block = blocks[index]
    body = _comment_body(block)
    if body:
        footer = comment_footer(input_data) if isinstance(input_data, dict) else ''
        if footer and footer not in body:
            body += '\n\n' + footer
    return {'title': _finding_title(block) or f'Finding {index + 1}', 'body': body or '',
            'markdown': '\n'.join(block), 'head': report_head,
            'artifact': artifact, 'target': None}


def finding(url, revision, version, finding_id):
    canonical, _, _ = github.identity(url)
    comparison = github.cached(canonical, revision)
    item = _finding_artifact(canonical, comparison['head'], version, finding_id)
    target = _report_target(item['markdown'], comparison)
    stale = item['head'] != comparison['head']
    return {'finding': str(finding_id), 'title': item['title'], 'body': item['body'],
            'target': target, 'stale': stale, 'can_post': bool(item['body']) and not stale,
            'head': item['head'], 'current_head': comparison['head'], 'version': version,
            'notice': ('This finding is from an older commit. Ask AI can still explain it, '
                       'but posting is disabled until the report is current.') if stale else ''}


def post_finding(url, request):
    if not isinstance(request, dict):
        raise ValueError('Expected a comment request.')
    revision = request.get('revision')
    version = request.get('version')
    finding_id = request.get('finding')
    canonical, _, _ = github.identity(url)
    preview = finding(canonical, revision, version, finding_id)
    if not preview['can_post']:
        raise ValueError(preview['notice'] or 'This finding has no copyable draft.')
    body = request.get('body') or preview['body']
    if not isinstance(body, str) or not body.strip():
        raise ValueError('Comment must contain text.')
    result = comments.post(canonical, {'revision': revision, 'body': body, 'target': preview['target']})
    return {**result, 'finding': preview['finding'], 'target': preview['target']['mode']}


def review(url, head):
    runs, _ = tracker.load_all_runs(dashboard.STALE_RUN_HOURS)
    runs = [r for r in runs if r['pr_url'] == url]
    artifacts = runtime.collect_artifacts(runs, head)
    artifact = artifacts.get('review-html') or artifacts.get('review-markdown')
    latest = max(runs, key=lambda r: r.get('created_at', ''), default=None)
    # Continue the session that wrote the shown report, not a newer failed run.
    source = next((r for r in runs if artifact and r['run_id'] == artifact['run_id']), None)
    return {'artifact': artifact, 'run': runtime.summarize_run(latest, head) if latest else None,
            'update_check': update_check(url, head, runs),
            'continuation': review_continuation.continuation(
                source, runtime.summarize_run(source)['status']) if source else None}


def artifact_for_head(url, report_head):
    """Find the saved review artifact for an explicitly selected report revision."""
    if not SHA.fullmatch(str(report_head or '')):
        return None
    runs, _ = tracker.load_all_runs(dashboard.STALE_RUN_HOURS)
    runs = [r for r in runs if r.get('pr_url') == url]
    for run in sorted(runs, key=lambda r: r.get('created_at', ''), reverse=True):
        artifacts = runtime.collect_artifacts([run], report_head)
        for name in ('review-html', 'review-markdown'):
            artifact = artifacts.get(name)
            if artifact and artifact.get('head_sha') == report_head:
                return artifact
    return None


def update_check(url, head, runs):
    import dashboard_triage
    import review_update
    prior = review_update.prior_reviews(runs).get(url)
    return dashboard_triage.update_view(url, {'head_sha': head}, prior)


def load(url, rev=None, progress=None):
    comparison = github.cached(url, rev) if rev else github.manifest(url, progress)
    if rev:
        private = store.ensure_note_metadata(url)
    else:
        store.reconcile(url, comparison)
        private = store.ensure_note_metadata(url)
    return {**comparison, 'chat_config': ai_settings.selected('chat'), 'saved': {**private, 'viewed': [f['path'] for f in comparison['files'] if private['viewed'].get(f['path']) == f['fingerprint']], 'threads': chat.conversations(url)},
            'review': review(comparison['url'], comparison['head'])}


def save(url, request):
    comparison = github.cached(url, request.get('revision'))
    state = store.save(url, comparison, request)
    return {'version': state['version']}

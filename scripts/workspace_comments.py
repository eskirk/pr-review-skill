"""GitHub review threads and PR conversation through authenticated gh."""
import json
import re
import subprocess
import time
import pr_dashboard as dashboard
import pr_review_tracker as tracker
import workspace_github as github
import workspace_store as store

MAX_PAGES = 10
MAX_BODY = 20_000
FRESH_SECONDS = 60
AUTHOR = 'author{login __typename} authorAssociation'
PR = 'query($owner:String!,$name:String!,$number:Int!,$cursor:String){viewer{login} repository(owner:$owner,name:$name){pullRequest(number:$number){headRefOid %s}}}'
THREADS = PR % ('reviewThreads(first:100,after:$cursor){pageInfo{hasNextPage endCursor} nodes{id isResolved isOutdated path line startLine originalLine originalStartLine diffSide subjectType '
                'comments(first:50){totalCount nodes{id ' + AUTHOR + ' body createdAt url diffHunk}}}}')
COMMENTS = PR % ('comments(first:100,after:$cursor){pageInfo{hasNextPage endCursor} nodes{id ' + AUTHOR + ' body createdAt url}}')
REVIEWS = PR % ('reviews(first:100,after:$cursor){pageInfo{hasNextPage endCursor} nodes{id ' + AUTHOR + ' body state submittedAt url}}')


def graphql(query, variables):
    """Only queries are sent; this module never mutates GitHub."""
    command = [dashboard.gh_executable(), 'api', 'graphql', '-f', 'query=' + query]
    for key, value in variables.items():
        if value is not None:
            command += ['-F' if isinstance(value, int) else '-f', f'{key}={value}']
    try:
        result = subprocess.run(command, capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ValueError('GitHub is unavailable or timed out. Check gh authentication and retry.') from error
    if result.returncode:
        raise ValueError('GitHub could not read this PR’s comments. Check access and gh authentication.')
    try:
        return json.loads(result.stdout)['data']
    except (ValueError, UnicodeError, KeyError, TypeError) as error:
        raise ValueError('GitHub returned invalid comment data.') from error


def connection(query, variables, name):
    nodes, cursor, data = [], None, None
    for _ in range(MAX_PAGES):
        data = graphql(query, {**variables, 'cursor': cursor})
        page = data['repository']['pullRequest'][name]
        nodes.extend(page['nodes'])
        if not page['pageInfo']['hasNextPage']:
            return nodes, data, False
        cursor = page['pageInfo']['endCursor']
    return nodes, data, True


def person(node):
    author = node.get('author') or {}
    login = author.get('login') or 'ghost'
    body = node.get('body') or ''
    return {'id': node['id'], 'author': login, 'bot': author.get('__typename') == 'Bot' or login.endswith('[bot]'),
            'association': node.get('authorAssociation') or '', 'body': body[:MAX_BODY],
            'truncated': len(body) > MAX_BODY, 'created_at': node.get('createdAt') or node.get('submittedAt') or '',
            'url': node.get('url') or ''}


def thread(node):
    comments = node['comments']
    side = 'base' if node.get('diffSide') == 'LEFT' else 'head'
    return {'id': node['id'], 'path': node['path'], 'side': side, 'line': node.get('line'),
            'start_line': node.get('startLine'), 'original_line': node.get('originalLine'),
            'outdated': bool(node.get('isOutdated')), 'resolved': bool(node.get('isResolved')),
            'file_level': node.get('subjectType') == 'FILE',
            'diff_hunk': (comments['nodes'][0].get('diffHunk') or '')[-4000:] if comments['nodes'] else '',
            'hidden_comments': max(0, comments['totalCount'] - len(comments['nodes'])),
            'comments': [person(c) for c in comments['nodes']]}


def fetch(url):
    url, repo, number = github.identity(url)
    owner, name = repo.split('/')
    variables = {'owner': owner, 'name': name, 'number': int(number)}
    threads, data, more_threads = connection(THREADS, variables, 'reviewThreads')
    comments, _, more_comments = connection(COMMENTS, variables, 'comments')
    reviews, _, more_reviews = connection(REVIEWS, variables, 'reviews')
    conversation = [{**person(c), 'kind': 'comment'} for c in comments]
    conversation += [{**person(r), 'kind': 'review', 'state': r.get('state') or ''}
                     for r in reviews if (r.get('body') or '').strip()]
    conversation.sort(key=lambda item: item['created_at'])
    return {'url': url, 'head': data['repository']['pullRequest']['headRefOid'],
            'viewer': (data.get('viewer') or {}).get('login') or '', 'fetched_at': time.time(),
            'incomplete': more_threads or more_comments or more_reviews,
            'threads': [thread(t) for t in threads], 'conversation': conversation}


def path(url):
    return store.directory(url) / 'comments.json'


def cached(url):
    return tracker.read_json(path(url), required=False) or None


def load(url, refresh=False):
    """Serve a recent cache; otherwise read GitHub again and replace it atomically."""
    current = cached(url)
    if current and not refresh and time.time() - current.get('fetched_at', 0) < FRESH_SECONDS:
        return current
    result = fetch(url)
    tracker.atomic_write(path(url), result)
    return result


def find(url, item_id):
    comments = cached(url)
    if not comments or not isinstance(item_id, str):
        raise ValueError('Reload comments before asking about them.')
    for item in comments['threads']:
        if item['id'] == item_id:
            return comments, item, 'thread'
    for item in comments['conversation']:
        if item['id'] == item_id:
            return comments, item, 'conversation'
    raise ValueError('This comment is no longer available. Refresh comments and retry.')


SHA = re.compile(r'^[0-9a-f]{40}$')
MAX_POST_BODY = 20_000


def _integer(value, label):
    if type(value) is not int or value < 1:
        raise ValueError(f'Invalid {label}.')
    return value


def _repository_path(value):
    if (not isinstance(value, str) or not value or value.startswith('/') or
            any(part in ('.', '..') for part in value.split('/')) or '\x00' in value):
        raise ValueError('Choose a repository-relative source path.')
    return value


def _gh_post(args, kind):
    try:
        result = subprocess.run([dashboard.gh_executable(), 'api', *args],
                                capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ValueError('GitHub is unavailable or timed out. Check gh authentication and retry.') from error
    if result.returncode:
        # Do not echo GitHub CLI output: it can contain repository text or credential-shaped data.
        raise ValueError(f'GitHub could not post this {kind}. Check access and gh authentication.')
    try:
        value = json.loads(result.stdout) if result.stdout else {}
    except (ValueError, UnicodeError):
        value = {}
    return value if isinstance(value, dict) else {}


def post(url, request):
    """Publish one user-confirmed prepared finding comment through gh.

    The browser supplies only a target derived from the pinned workspace report;
    the endpoint revalidates the PR and current head before invoking GitHub.
    """
    if not isinstance(request, dict):
        raise ValueError('Expected a comment request.')
    body = request.get('body')
    if not isinstance(body, str) or not body.strip() or len(body) > MAX_POST_BODY or '\x00' in body:
        raise ValueError('Comment must contain between 1 and 20,000 characters.')
    target = request.get('target')
    if not isinstance(target, dict):
        raise ValueError('Choose a review thread or source location.')
    canonical, repo, number = github.identity(url)
    revision = request.get('revision')
    comparison = github.cached(canonical, revision)
    mode = target.get('mode')
    if mode == 'reply':
        comment_id = _integer(target.get('in_reply_to'), 'review comment')
        # GitHub's reply endpoint accepts the parent comment ID as in_reply_to
        # on the collection endpoint; the /comments/{id}/replies path is not
        # available on all GitHub Enterprise versions.
        value = _gh_post([f'repos/{repo}/pulls/{number}/comments',
                          '--method', 'POST', '-f', f'body={body}',
                          '-F', f'in_reply_to={comment_id}'], 'reply')
    elif mode == 'inline':
        commit_id = target.get('commit_id')
        if not isinstance(commit_id, str) or not SHA.fullmatch(commit_id) or commit_id != comparison['head']:
            raise ValueError('The review location is not from the pinned pull request head.')
        source_path = _repository_path(target.get('path'))
        file = next((item for item in comparison['files']
                     if item.get('path') == source_path or item.get('previous') == source_path), None)
        if file is None:
            raise ValueError('The review location is not part of this pull request.')
        # GitHub expects the new path for a renamed file, even for a left-side line.
        source_path = file['path']
        side = target.get('side')
        if side not in ('LEFT', 'RIGHT'):
            raise ValueError('Invalid review side.')
        line = _integer(target.get('line'), 'review line')
        args = [f'repos/{repo}/pulls/{number}/comments', '--method', 'POST',
                '-f', f'body={body}', '-f', f'commit_id={commit_id}',
                '-f', f'path={source_path}', '-F', f'line={line}', '-f', f'side={side}']
        if target.get('start_line') is not None:
            start_line = _integer(target.get('start_line'), 'review start line')
            if start_line > line:
                raise ValueError('Review start line must not follow the end line.')
            args += ['-F', f'start_line={start_line}', '-f', f'start_side={side}']
        value = _gh_post(args, 'comment')
    elif mode == 'conversation':
        value = _gh_post([f'repos/{repo}/issues/{number}/comments',
                          '--method', 'POST', '-f', f'body={body}'], 'comment')
    else:
        raise ValueError('Choose a review thread or source location.')
    # A successful post makes the old read cache misleading; the next rail load refreshes it.
    try:
        path(canonical).unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass
    return {'posted': True, 'id': value.get('id'), 'url': value.get('html_url') or value.get('url') or ''}

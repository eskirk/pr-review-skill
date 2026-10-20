"""Durable personal review intent and read-only GitHub follow-up signals."""
from __future__ import annotations

import copy
import json
import re
import secrets
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import pr_dashboard as dashboard
import pr_review_tracker as tracker

STAGES = {'up_next', 'reviewing', 'waiting', 'done', 'removed', 'history'}
ACTIVE = {'up_next', 'reviewing', 'waiting'}
# Stage moves record why the PR moved and can be undone from the confirmation toast.
MOVES = {'start', 'stop', 'wait', 'acknowledge', 'remove', 'restore', 'snooze'}
UNDO_KEYS = ('stage', 'done_at', 'review_observation', 'ack_head', 'ack_at', 'ack_event_ids',
             'position', 'moved', 'remind_at', 'snoozed_until', 'snooze_baseline')
REMIND_DAYS = {1, 3, 7}
# Your-turn PRs can be snoozed; waiting PRs use reminders instead.
SNOOZABLE = {'up_next', 'reviewing'}
# Unchanged open PRs skip the detailed fetch, but each still gets one full check per hour.
FULL_CHECK_SECONDS = 3600
BATCH_SIZE = 25
_state = threading.Lock()
_running = False
_rerun = False
_status = {'status': 'idle'}
_triage_after_refresh = False
_fetching = set()


def load():
    data = tracker.read_json(tracker.tracker_root() / 'my-reviews.json', required=False)
    data.setdefault('version', 1)
    data.setdefault('prs', {})
    data.setdefault('candidates', {})
    for record in data['prs'].values():
        if record.get('stage') in ('done', 'history'):
            record['stage'] = 'waiting'
    return data


def save(data):
    tracker.atomic_write(tracker.tracker_root() / 'my-reviews.json', data)


def epoch(stamp):
    try:
        return datetime.fromisoformat(stamp.replace('Z', '+00:00')).timestamp()
    except (ValueError, TypeError, AttributeError):
        return 0


def identity(url):
    canonical, owner, repo, number = tracker.canonical_pr_url(url)
    return canonical, {'owner': owner, 'repository': repo, 'number': number,
                       'title': f'{owner}/{repo} #{number}', 'first_seen_at': tracker.utc_now()}


def observed(record):
    return {'head_sha': record.get('metadata', {}).get('head_sha', ''),
            'at': record.get('checked_at', ''),
            'event_ids': [event['id'] for event in record.get('events', [])
                          if epoch(event['at']) >= epoch(record.get('checked_at'))]}


def acknowledge(record, observation):
    if not isinstance(observation, dict):
        raise dashboard.DashboardError('Reload this PR before acknowledging updates.')
    head, at, ids = observation.get('head_sha', ''), observation.get('at', ''), observation.get('event_ids', [])
    if not isinstance(head, str) or (head and not re.fullmatch(r'[a-fA-F0-9]{40,64}', head)) or not isinstance(ids, list) or len(ids) > 10000:
        raise dashboard.DashboardError('Invalid review observation.')
    if any(not isinstance(i, str) or len(i) > 100 for i in ids):
        raise dashboard.DashboardError('Invalid review event.')
    if not epoch(at):
        raise dashboard.DashboardError('Refresh this PR before marking its updates checked.')
    if epoch(at) < epoch(record.get('ack_at')):
        raise dashboard.DashboardError('This review observation is older than your last acknowledgment. Reload and try again.')
    record.update(ack_head=head, ack_at=at, ack_event_ids=ids)


def reminder_due(record):
    return bool(record.get('remind_at')) and epoch(record['remind_at']) <= epoch(tracker.utc_now())


def unsnooze(record):
    record.pop('snoozed_until', None)
    record.pop('snooze_baseline', None)


def days_from(now, days):
    return (datetime.fromisoformat(now.replace('Z', '+00:00')) + timedelta(days=days)).isoformat(timespec='seconds')


def valid_days(days):
    return isinstance(days, int) and not isinstance(days, bool) and days in REMIND_DAYS


def mutate(url, action, payload=None):
    payload = payload or {}
    canonical, fallback = identity(url)
    if action == 'done':
        action = 'wait'  # Compatibility with an already-open older dashboard.
    with dashboard.state_lock():
        data = load()
        record = data['prs'].get(canonical)
        if action == 'enqueue':
            if record and record['stage'] in ACTIVE:
                return {'ok': True, 'existing': True}
            metadata = {**fallback, **data['candidates'].get(canonical, {}),
                        **dashboard.load_dashboard()['prs'].get(canonical, {})}
            now = tracker.utc_now()
            previous = record or {}
            # Enrolling again is deliberate; a removed record never enrolls itself.
            record = {**previous, 'stage': 'waiting' if payload.get('recover') is True else 'up_next',
                      'metadata': {**metadata, **previous.get('metadata', {})},
                      'created_at': now, 'action_at': now, 'position': max(
                          (r.get('position', 0) for r in data['prs'].values()), default=0) + 1,
                      'note': previous.get('note', ''), 'ack_at': now, 'ack_event_ids': [],
                      'ack_head': metadata.get('head_sha', ''), 'revision': previous.get('revision', 0) + 1}
            record.pop('undo', None)
            record.pop('review_observation', None)
            record.pop('remind_at', None)
            unsnooze(record)
            record['moved'] = {'kind': 'recovered' if payload.get('recover') is True else 'added', 'at': now}
            record['ack_head'] = record['metadata'].get('head_sha', '')
            if payload.get('recover') is True:
                record['recover_baseline'] = True
                record['ack_at'] = metadata.get('my_review_at') or metadata.get('my_comment_at') or now
                record['ack_head'] = ''
            data['prs'][canonical] = record
            save(data)
            return {'ok': True}
        if not record:
            raise dashboard.DashboardError('Add this PR to My reviews first.')
        if payload.get('revision') != record.get('revision'):
            raise dashboard.DashboardError('This PR changed in another action. Reload and try again; your changes were not overwritten.')
        if action == 'undo':
            undo = record.get('undo')
            if not undo or not secrets.compare_digest(str(payload.get('token', '')), undo['token']):
                raise dashboard.DashboardError('Undo is no longer available. Use Add PR to track it again.')
            for key, value in undo['before'].items():
                if value is None:
                    record.pop(key, None)
                else:
                    record[key] = value
            record.pop('undo', None)
        elif action in ('start', 'stop', 'wait', 'acknowledge', 'remove', 'note', 'restore', 'move_up', 'remind', 'snooze'):
            before = {key: copy.deepcopy(record.get(key)) for key in UNDO_KEYS}
            now = tracker.utc_now()
            if action == 'note':
                note = payload.get('note', '')
                if not isinstance(note, str) or len(note) > 4000:
                    raise dashboard.DashboardError('Keep the private note under 4,000 characters.')
                record['note'] = note
            elif action == 'start':
                observation = payload.get('observed') or observed(record)
                if not isinstance(observation, dict) or not observation.get('head_sha') or not epoch(observation.get('at')):
                    raise dashboard.DashboardError('Check for updates first so this review starts at a known commit.')
                record['moved'] = {'kind': 'started' if record['stage'] == 'up_next' else 'resumed', 'at': now}
                # Continuing a snoozed review keeps the commit it started at.
                if record['stage'] != 'reviewing' or not record.get('review_observation'):
                    record['review_observation'] = copy.deepcopy(observation)
                record['stage'] = 'reviewing'
                record.pop('remind_at', None)
                unsnooze(record)
            elif action == 'stop':
                if record['stage'] != 'reviewing':
                    raise dashboard.DashboardError('This PR is not currently being reviewed.')
                # Pausing puts the PR back at the top of Up next.
                record['position'] = min((r.get('position', 0) for r in data['prs'].values()
                                          if r['stage'] == 'up_next'), default=1) - 1
                record['stage'] = 'up_next'
                record['moved'] = {'kind': 'paused', 'at': now}
                record.pop('review_observation', None)
                unsnooze(record)
            elif action == 'wait':
                acknowledge(record, record.get('review_observation') or payload.get('observed'))
                record['stage'] = 'waiting'
                record['moved'] = {'kind': 'handed_back', 'at': now}
                record.pop('review_observation', None)
                record.pop('remind_at', None)
                unsnooze(record)
            elif action == 'acknowledge':
                acknowledge(record, payload.get('observed'))
                if record['stage'] == 'reviewing':
                    record['review_observation'] = copy.deepcopy(payload['observed'])
                elif record['stage'] == 'waiting':
                    record['moved'] = {'kind': 'kept_waiting', 'at': now}
                    if reminder_due(record):
                        record.pop('remind_at', None)
            elif action == 'remove':
                record['stage'] = 'removed'
                record['done_at'] = now
                record['moved'] = {'kind': 'removed', 'at': now}
                record.pop('remind_at', None)
                unsnooze(record)
            elif action == 'restore':
                record['stage'] = 'up_next'
                record['moved'] = {'kind': 'restored', 'at': now}
                record.pop('remind_at', None)
                unsnooze(record)
            elif action == 'remind':
                days = payload.get('days')
                if record['stage'] != 'waiting':
                    raise dashboard.DashboardError('Reminders are only available while waiting for the author.')
                if days == 0:
                    record.pop('remind_at', None)
                elif valid_days(days):
                    record['remind_at'] = days_from(now, days)
                else:
                    raise dashboard.DashboardError('Choose a reminder of 1, 3 or 7 days.')
            elif action == 'snooze':
                days = payload.get('days')
                if record['stage'] not in SNOOZABLE:
                    raise dashboard.DashboardError('Snooze is available in Up next and In progress. Use Remind me while waiting for the author.')
                if days == 0:
                    if not record.get('snoozed_until'):
                        raise dashboard.DashboardError('This PR is not snoozed.')
                    unsnooze(record)
                    record['moved'] = {'kind': 'unsnoozed', 'at': now}
                elif valid_days(days):
                    # Activity after this point ends the snooze early.
                    record['snoozed_until'] = days_from(now, days)
                    record['snooze_baseline'] = {'head_sha': record.get('metadata', {}).get('head_sha', ''),
                                                 'event_ids': [e['id'] for e in record.get('events', [])]}
                    record['moved'] = {'kind': 'snoozed', 'at': now}
                else:
                    raise dashboard.DashboardError('Choose a snooze of 1, 3 or 7 days.')
            elif action == 'move_up':
                peers = sorted(((u, r) for u, r in data['prs'].items() if r['stage'] == 'up_next'),
                               key=lambda pair: pair[1].get('position', 0))
                index = next((i for i, (u, _) in enumerate(peers) if u == canonical), 0)
                if index:
                    other = peers[index-1][1]
                    record['position'], other['position'] = other['position'], record['position']
                    other['revision'] += 1
        else:
            raise dashboard.DashboardError('Unknown personal review action.')
        if action in MOVES:
            record['undo'] = {'token': secrets.token_urlsafe(16), 'before': before}
        record['revision'] += 1
        record['action_at'] = tracker.utc_now()
        if action not in ('note', 'move_up'):
            record.pop('recover_baseline', None)
        save(data)
        return {'ok': True, 'revision': record['revision'], 'undo_token': record.get('undo', {}).get('token')}


def snooze_ended(record, head, events):
    """A snooze ends when it is due, or earlier on a new commit or new activity."""
    baseline = record.get('snooze_baseline') or {}
    seen = set(baseline.get('event_ids', []))
    due = epoch(record['snoozed_until']) <= epoch(tracker.utc_now())
    active = bool(head and baseline.get('head_sha') and head != baseline['head_sha']) or any(e['id'] not in seen for e in events)
    return due, due or active


def presentation(record):
    metadata = record.get('metadata', {})
    stage = 'waiting' if record['stage'] in ('done', 'history') else record['stage']
    closed = metadata.get('pr_state') in ('closed', 'merged')
    events = [e for e in record.get('events', []) if epoch(e['at']) >= epoch(record.get('ack_at'))
              and e['id'] not in record.get('ack_event_ids', [])]
    reasons = []
    head = metadata.get('head_sha', '')
    if stage in ACTIVE and head and record.get('ack_head') and head != record['ack_head']:
        reasons.append({'kind': 'head', 'label': 'Head changed since saved' if stage == 'up_next' else 'Head changed since your last check',
                        'url': f"https://github.com/{metadata['owner']}/{metadata['repository']}/compare/{record['ack_head']}...{head}"})
    for kind, label in [('reply', 'Reply in your review thread'), ('author', 'Author commented'),
                        ('mention', 'You were mentioned'), ('requested', 'Review requested again')]:
        matching = [e for e in events if e['kind'] == kind]
        if matching:
            reasons.append({'kind': kind, 'label': label, 'url': matching[-1]['url']})
    pr_link = f"https://github.com/{metadata.get('owner')}/{metadata.get('repository')}/pull/{metadata.get('number')}"
    if stage == 'waiting' and reminder_due(record):
        reasons.append({'kind': 'reminder', 'label': 'Your reminder is due', 'url': pr_link})
    snoozed = stage in SNOOZABLE and bool(record.get('snoozed_until'))
    due, woken = snooze_ended(record, head, events) if snoozed else (False, False)
    if due:
        reasons.append({'kind': 'snooze', 'label': 'Your snooze ended', 'url': pr_link})
    if closed or stage in ('removed', 'history'):
        reasons = []
    bucket = 'history' if closed else 'removed' if stage == 'removed' else (
        'attention' if (reasons and stage == 'waiting') or woken else 'snoozed' if snoozed else stage)
    return {key: record.get(key) for key in ('stage', 'revision', 'note', 'created_at', 'position',
            'checked_at', 'attempted_at', 'error', 'review_observation', 'moved', 'remind_at',
            'snoozed_until', 'action_at')} | {
                'bucket': bucket, 'reasons': reasons, 'observed': observed(record), 'closed': closed,
                'stage': stage, 'in_history': closed}


def merged_entries(entries, data=None):
    data = data if data is not None else load()
    result = copy.deepcopy(entries)
    for url, record in data['prs'].items():
        # Removed entries remain in personal history, but never become discovery results.
        metadata = {k:v for k,v in record.get('metadata', {}).items() if k not in (
            'hidden', 'starred', 'snoozed_until', 'reasons', 'sources', 'starred_at', 'hidden_at')}
        result[url] = {**result.get(url, {}), **metadata,
                       'discovered': url in entries, 'workflow': presentation(record)}
    for url in entries:
        result[url].setdefault('discovered', True)
    return result


def api(path, paginated=False):
    args = [dashboard.gh_executable(), 'api', '--method', 'GET', path]
    if paginated:
        args += ['--paginate', '--slurp']
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=60, check=False)
        if result.returncode:
            raise dashboard.DashboardError('GitHub could not be checked. Verify repository access and GitHub CLI sign-in, then retry.')
        payload = json.loads(result.stdout)
        if paginated:
            if not isinstance(payload, list) or any(not isinstance(page, list) for page in payload):
                raise ValueError('Incomplete paginated response')
            return [item for page in payload for item in page]
        if not isinstance(payload, dict):
            raise ValueError('Invalid response')
        return payload
    except (OSError, subprocess.TimeoutExpired, ValueError) as error:
        raise dashboard.DashboardError('GitHub returned incomplete data. Your saved review was kept; retry the refresh.') from error


def classify(url, login, pr, comments, discussion, requests, reviews):
    canonical, metadata = identity(url)
    author = (pr.get('user') or {}).get('login', '')
    metadata.update(title=pr.get('title') or metadata['title'], author_login=author,
                    author_avatar_url=(pr.get('user') or {}).get('avatar_url', ''),
                    is_draft=bool(pr.get('draft')), head_sha=pr.get('head', {}).get('sha', ''),
                    base_sha=pr.get('base', {}).get('sha', ''),
                    pr_updated_at=pr.get('updated_at', ''), pr_created_at=pr.get('created_at', ''),
                    pr_state='merged' if pr.get('merged_at') else pr.get('state', ''),
                    closed_at=pr.get('closed_at') or '', merged_at=pr.get('merged_at') or '')
    metadata.update({key: pr[key] for key in ('additions', 'deletions', 'changed_files') if isinstance(pr.get(key), int)})
    import dashboard_triage
    metadata['triage_context_hash'] = dashboard_triage.context_hash(pr.get('title') or metadata['title'], pr.get('body') or '')
    mine = lambda item: (item.get('user') or {}).get('login', '').lower() == login.lower()
    my_reviews = [r for r in reviews if mine(r) and r.get('submitted_at') and r.get('state') != 'PENDING']
    latest = max(my_reviews, key=lambda r: epoch(r['submitted_at']), default={})
    my_comments = [c for c in [*discussion, *comments] if mine(c)]
    metadata.update(my_review_at=latest.get('submitted_at', ''), my_review_state=latest.get('state', ''),
                    my_comment_at=max((c.get('created_at', '') for c in my_comments), key=epoch, default=''))
    events, threads = [], {}
    for c in comments:
        if mine(c):
            root = c.get('in_reply_to_id') or c.get('id')
            threads[root] = min(threads.get(root, float('inf')), epoch(c.get('created_at')))
    def add(item, kind, prefix):
        events.append({'id': prefix + str(item['id']), 'at': item['created_at'], 'kind': kind,
                       'url': item.get('html_url') or canonical})
    def human(item):
        user = item.get('user') or {}
        return user.get('login') and not mine(item) and user.get('type') != 'Bot' and not user['login'].endswith('[bot]')
    mention = re.compile(r'(?<![\w-])@' + re.escape(login) + r'(?![\w-])', re.I)
    for c in comments:
        if not human(c):
            continue
        root = c.get('in_reply_to_id') or c.get('id')
        if root in threads and epoch(c.get('created_at')) > threads[root]:
            add(c, 'reply', 'thread:')
        elif mention.search(c.get('body') or ''):
            add(c, 'mention', 'thread:')
    feedback_at = min((epoch(c.get('created_at') or c.get('submitted_at')) for c in [*my_comments, *my_reviews]), default=float('inf'))
    for c in discussion:
        if not human(c):
            continue
        if mention.search(c.get('body') or ''):
            add(c, 'mention', 'comment:')
        elif (c.get('user') or {}).get('login') == author and epoch(c.get('created_at')) > feedback_at:
            add(c, 'author', 'comment:')
    for event in requests:
        if event.get('event') == 'review_requested' and (event.get('requested_reviewer') or {}).get('login', '').lower() == login.lower():
            add(event, 'requested', 'request:')
    return {'metadata': metadata, 'events': sorted(events, key=lambda e: (epoch(e['at']), e['id'])), 'latest_review': latest}


def fetch_pr(url, login):
    _, owner, repo, number = tracker.canonical_pr_url(url)
    base = f'repos/{owner}/{repo}'
    # Sequential requests within a PR; the outer refresh bounds PR concurrency.
    pr = api(f'{base}/pulls/{number}')
    comments = api(f'{base}/pulls/{number}/comments?per_page=100', True)
    discussion = api(f'{base}/issues/{number}/comments?per_page=100', True)
    requests = api(f'{base}/issues/{number}/events?per_page=100', True)
    reviews = api(f'{base}/pulls/{number}/reviews?per_page=100', True)
    return classify(url, login, pr, comments, discussion, requests, reviews)


def apply_fetch(url, payload, started, error=None):
    with dashboard.state_lock():
        data = load()
        record = data['prs'].get(url)
        if not record:
            return
        if epoch(record.get('created_at')) > epoch(started):
            return
        record['attempted_at'] = started
        if error:
            record['error'] = str(error)
        else:
            # A slower overlapping refresh cannot overwrite a newer observation.
            if epoch(started) < epoch(record.get('checked_at')):
                return
            record['metadata'] = {**record.get('metadata', {}), **payload['metadata']}
            # Search results also update metadata, so keep what the detailed fetch saw separately.
            record['fetched'] = {'updated_at': payload['metadata'].get('pr_updated_at', ''),
                                 'head_sha': payload['metadata'].get('head_sha', '')}
            record.update(events=payload['events'], checked_at=started, error='')
            latest = payload.get('latest_review') or {}
            if record.pop('recover_baseline', False) and latest.get('commit_id'):
                record['ack_head'] = latest['commit_id']
                record['ack_at'] = latest['submitted_at']
            elif not record.get('ack_head'):
                record['ack_head'] = payload['metadata'].get('head_sha', '')
            # Only genuinely new submitted reviews can move an active human review.
            if (record['stage'] == 'reviewing' and latest.get('commit_id')
                    and epoch(latest.get('submitted_at')) > epoch(record.get('action_at'))):
                record.update(stage='waiting', ack_head=latest['commit_id'], ack_at=latest['submitted_at'],
                              ack_event_ids=[], action_at=latest['submitted_at'], revision=record['revision'] + 1,
                              moved={'kind': 'github_review', 'at': latest['submitted_at']})
                record.pop('review_observation', None)
                record.pop('undo', None)
                unsnooze(record)
        save(data)


HISTORY_DAYS = tracker.RUN_RETENTION_DAYS  # inbox history, notes, chats and review runs expire together


def participated(metadata):
    return bool(metadata.get('history_participated') or metadata.get('my_review_at') or metadata.get('my_comment_at'))


def expired(metadata, now=None):
    if metadata.get('pr_state') not in ('closed', 'merged'):
        return False
    closed = epoch(metadata.get('merged_at') or metadata.get('closed_at'))
    return bool(closed and (now or datetime.now(timezone.utc).timestamp()) - closed >= HISTORY_DAYS * 86400)


def discover_history(login, started):
    """Search actual participation; requests, mentions and AI runs alone do not count."""
    import dashboard_reporting as reporting
    since = (datetime.now(timezone.utc) - timedelta(days=HISTORY_DAYS)).date().isoformat()
    query = """query($query:String!,$cursor:String){
      search(query:$query,type:ISSUE,first:100,after:$cursor){issueCount
        pageInfo{hasNextPage endCursor} nodes{... on PullRequest{
          url title state closedAt mergedAt createdAt updatedAt isDraft
          headRefOid baseRefOid author{login avatarUrl}
        }}}}"""
    def search(search_query):
        found, cursor = {}, None
        while True:
            result = reporting.graphql(query, {'query': search_query, 'cursor': cursor})['search']
            if result['issueCount'] > 1000:
                raise dashboard.DashboardError('Participation history exceeds GitHub’s search limit. Previous history kept; search needs a narrower range.')
            for item in result['nodes']:
                if not item or not item.get('url'):
                    continue
                url, metadata = identity(item['url'])
                metadata.update(title=item['title'], author_login=(item.get('author') or {}).get('login', ''),
                    author_avatar_url=(item.get('author') or {}).get('avatarUrl', ''),
                    pr_state=item['state'].lower(), closed_at=item.get('closedAt') or '',
                    merged_at=item.get('mergedAt') or '', pr_updated_at=item['updatedAt'],
                    pr_created_at=item['createdAt'], is_draft=item['isDraft'],
                    head_sha=item['headRefOid'], base_sha=item['baseRefOid'], history_participated=True)
                found[url] = metadata
            page = result['pageInfo']
            if not page['hasNextPage']:
                return found
            if not page['endCursor'] or page['endCursor'] == cursor:
                raise dashboard.DashboardError('Incomplete participation history. Previous history kept; retry sync.')
            cursor = page['endCursor']
    searches = [f'is:pr {scope} {qualifier}:{login} -author:{login}'
                for qualifier in ('reviewed-by', 'commenter') for scope in ('is:open', 'is:closed closed:>=' + since)]
    found = {}
    with ThreadPoolExecutor(max_workers=len(searches)) as pool:
        for result in pool.map(search, searches):
            found.update(result)
    # Commit only after every search/page succeeds, merging concurrent local choices.
    with dashboard.state_lock():
        data = load()
        for url, metadata in found.items():
            record = data['prs'].get(url)
            if expired(metadata) and not record:
                continue
            if not record:
                record = {'stage': 'waiting', 'created_at': started, 'action_at': started,
                          'revision': 1, 'position': 0, 'note': '', 'ack_at': started,
                          'ack_head': metadata['head_sha'], 'ack_event_ids': [],
                          'moved': {'kind': 'discovered', 'at': started}}
                data['prs'][url] = record
            if epoch(record.get('checked_at')) > epoch(started):
                continue
            record['metadata'] = {**record.get('metadata', {}), **metadata}
            # Active records still need the detailed follow-up observation below.
            if record['stage'] == 'removed' or metadata['pr_state'] in ('closed', 'merged'):
                record.update(checked_at=started, attempted_at=started, error='')
        data.pop('candidates', None)
        save(data)
    return set(found)


def remote_versions(urls):
    """Read updatedAt and head for many PRs in a few GraphQL calls; unreadable batches are omitted."""
    import dashboard_reporting as reporting
    def batch(part):
        declarations, fields, variables = [], [], {}
        for i, url in enumerate(part):
            _, owner, repo, number = tracker.canonical_pr_url(url)
            declarations.append(f'$o{i}:String!,$r{i}:String!,$n{i}:Int!')
            fields.append(f'p{i}:repository(owner:$o{i},name:$r{i}){{pullRequest(number:$n{i}){{updatedAt headRefOid state}}}}')
            variables.update({f'o{i}': owner, f'r{i}': repo, f'n{i}': number})
        try:
            data = reporting.graphql('query(' + ','.join(declarations) + '){' + ' '.join(fields) + '}', variables)
        except dashboard.DashboardError:
            return {}  # Those PRs get the detailed fetch instead.
        return {url: pr for i, url in enumerate(part)
                if isinstance(pr := ((data.get(f'p{i}') or {}).get('pullRequest')), dict)}
    parts = [urls[i:i + BATCH_SIZE] for i in range(0, len(urls), BATCH_SIZE)]
    versions = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        for result in pool.map(batch, parts):
            versions.update(result)
    return versions


def unchanged(record, remote, now):
    """An open PR whose updatedAt and head match the last detailed fetch within the hour."""
    fetched = record.get('fetched') or {}
    # Records saved before PR sizes were recorded get one detailed fetch.
    return bool(remote and remote.get('state') == 'OPEN' and not record.get('error') and 'additions' in record.get('metadata', {})
                and fetched.get('updated_at') and epoch(fetched['updated_at']) == epoch(remote.get('updatedAt'))
                and fetched.get('head_sha') == remote.get('headRefOid')
                and now - epoch(record.get('checked_at')) < FULL_CHECK_SECONDS)


def fetch_one(url, login, started):
    try:
        apply_fetch(url, fetch_pr(url, login), started)
        return None
    except dashboard.DashboardError as error:
        apply_fetch(url, None, started, error)
        return str(error)


def refresh(full=False):
    started = tracker.utc_now()
    login = api('user').get('login')
    if not login:
        raise dashboard.DashboardError('Could not identify your GitHub account.')
    with dashboard.state_lock():
        current = load()
        if current.get('login') and current['login'].lower() != login.lower():
            raise dashboard.DashboardError('GitHub account changed. Sign in with ' + current['login'] + ' to refresh this personal queue.')
        current['login'] = login
        save(current)
    failures = []
    try:
        discovered = discover_history(login, started)
    except (dashboard.DashboardError, KeyError, TypeError) as error:
        failures.append(str(error))
        discovered = set()
    with dashboard.state_lock():
        data = load()
    # Search refreshes history cheaply. Missing records are checked directly so
    # removed/manual items still expire, and search-index lag cannot imply closure.
    urls = [u for u, r in data['prs'].items() if u not in discovered or
            (r['stage'] != 'removed' and r.get('metadata', {}).get('pr_state') not in ('closed', 'merged'))]
    if not full:
        # Closed PRs are always fetched so retention sees this refresh's observation.
        versions = remote_versions([u for u in urls if data['prs'][u].get('metadata', {}).get('pr_state') == 'open'])
        now = epoch(started)
        urls = [u for u in urls if not unchanged(data['prs'][u], versions.get(u), now)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        failures.extend(error for error in pool.map(lambda url: fetch_one(url, login, started), urls) if error)
    import dashboard_retention
    failures.extend(dashboard_retention.cleanup(started))
    import storage_cleanup
    try:
        # Storage problems are recorded in storage-cleanup.json, not shown as refresh failures.
        storage_cleanup.maintain()
    except Exception as error:  # never let housekeeping break a GitHub refresh
        print(f'Storage cleanup failed ({type(error).__name__})', file=sys.stderr)
    if failures:
        raise dashboard.DashboardError(' '.join(dict.fromkeys(failures)))


def recover():
    # Compatibility for old tabs: participation now populates History automatically.
    refresh(full=True)


def start_refresh(force=False, recovery=False, triage_after=False, manual=False):
    """Start the full queue refresh. A manual Sync during a running refresh queues one more pass."""
    global _status, _triage_after_refresh, _running, _rerun
    with _state:
        if triage_after:
            _triage_after_refresh = True
        if _running:
            if manual:
                # The running pass may predate the click, so observe GitHub once more afterwards.
                _rerun = True
                _status = {**_status, 'manual': True}
            return False
        last = epoch(_status.get('started_at'))
        if not force and datetime.now(timezone.utc).timestamp() - last < 300:
            return False
        _running = True
        _status = {'status': 'running', 'started_at': tracker.utc_now(), 'manual': manual}
    def worker():
        global _status, _triage_after_refresh, _running, _rerun
        while True:
            try:
                refresh(full=recovery)
                result = {'status': 'completed', 'finished_at': tracker.utc_now()}
            except Exception as error:
                result = {'status': 'failed', 'message': str(error)}
            with _state:
                if _rerun:
                    _rerun = False
                    _status = {**_status, 'started_at': tracker.utc_now()}
                    continue
                _status = {**_status, **result, 'manual': False}
                follow_up = _triage_after_refresh
                _triage_after_refresh = False
                _running = False
            break
        if follow_up:
            import dashboard_triage
            try:
                dashboard_triage.start()
            except ValueError:
                pass  # Triage start records its own visible failure state.
    threading.Thread(target=worker, daemon=True).start()
    return True


def start_fetch(urls):
    """Check only these tracked PRs, outside the full refresh and its Sync status."""
    tracked = load()['prs']
    with _state:
        pending = [u for u in dict.fromkeys(urls) if u in tracked and u not in _fetching]
        _fetching.update(pending)
    if not pending:
        return False
    def worker():
        started = tracker.utc_now()
        try:
            login = load().get('login') or api('user').get('login')
            if not login:
                raise dashboard.DashboardError('Could not identify your GitHub account.')
            with ThreadPoolExecutor(max_workers=4) as pool:
                list(pool.map(lambda url: fetch_one(url, login, started), pending))
        except dashboard.DashboardError as error:
            for url in pending:
                apply_fetch(url, None, started, error)
        finally:
            with _state:
                _fetching.difference_update(pending)
    threading.Thread(target=worker, daemon=True).start()
    return True


def status():
    return dict(_status)

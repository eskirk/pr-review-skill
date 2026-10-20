"""Serve a disposable My reviews queue with PRs in every section.

All data is synthetic and lives in a temporary tracker home. GitHub refresh,
triage, AI launches and terminals are disabled, so no real PR is read or changed.
"""
import _bootstrap  # Make this checkout's scripts and test helpers importable.

from datetime import datetime, timedelta, timezone
import os
import signal
import tempfile
from unittest.mock import patch

A, B = 'a' * 40, 'b' * 40


def ago(**delta):
    return (datetime.now(timezone.utc) - timedelta(**delta)).isoformat(timespec='seconds')


def ahead(**delta):
    return (datetime.now(timezone.utc) + timedelta(**delta)).isoformat(timespec='seconds')


# number, title, author, stage, moved kind, moved age, extra record fields
PRS = [
    (201, 'Session replay masking rules', 'kim-demo', 'reviewing', 'started', {'minutes': 40},
     {'note': 'Stopped at masking.ts: iframe selectors still open.', 'events': [('reply', {'minutes': 10})]}),
    (202, 'Retry temporary image upload failures', 'ava-demo', 'waiting', 'handed_back', {'days': 3},
     {'head': B, 'events': [('author', {'hours': 2})], 'note': 'Author promised a retry limit.'}),
    (203, 'Fix race in cache eviction', 'leo-demo', 'waiting', 'handed_back', {'days': 1},
     {'events': [('reply', {'minutes': 35})]}),
    (204, 'Add keyboard navigation to the date picker', 'leo-demo', 'up_next', 'added', {'days': 1}, {}),
    (205, 'Bump build dependencies', 'renovate-demo', 'up_next', 'added', {'hours': 5}, {}),
    (206, 'Stream OTLP batches instead of buffering', 'sam-demo', 'up_next', 'paused', {'days': 2},
     {'note': 'Wait for the design doc link.'}),
    (207, 'Refactor exporter config loading', 'sam-demo', 'waiting', 'handed_back', {'days': 3},
     {'note': 'Asked for a test for empty config.'}),
    (208, 'Print friendlier auth errors', 'kim-demo', 'waiting', 'discovered', {'days': 6}, {}),
    (209, 'Add --json output flag', 'ava-demo', 'waiting', 'handed_back', {'days': 4}, {'closed': 'merged'}),
    (210, 'Experimental theming API', 'sam-demo', 'removed', 'removed', {'days': 4}, {}),
    (211, 'Document sampling defaults', 'ava-demo', 'up_next', 'snoozed', {'hours': 3}, {'snoozed': {'days': 2}}),
]


def seed(queue, dashboard):
    data = queue.load()
    now = ago()
    for position, (number, title, author, stage, kind, age, extra) in enumerate(PRS, 1):
        url = f'https://github.com/demo/workbench/pull/{number}'
        at = ago(**age)
        state = extra.get('closed', 'open')
        metadata = {'owner': 'demo', 'repository': 'workbench', 'number': number, 'title': title,
                    'author_login': author, 'head_sha': extra.get('head', A), 'base_sha': 'c' * 40,
                    'pr_state': state, 'pr_created_at': ago(days=position + 2), 'pr_updated_at': at,
                    'merged_at': at if state == 'merged' else '', 'closed_at': at if state != 'open' else '',
                    'first_seen_at': at}
        events = [{'id': f'{event}:{number}:{index}', 'kind': event, 'at': ago(**when),
                   'url': f'{url}#discussion_r{index}'} for index, (event, when) in enumerate(extra.get('events', []))]
        data['prs'][url] = {'stage': stage, 'metadata': metadata, 'events': events, 'created_at': at,
                            'action_at': at, 'position': position, 'note': extra.get('note', ''),
                            'revision': 1, 'ack_head': A, 'ack_at': at, 'ack_event_ids': [],
                            'checked_at': now, 'attempted_at': now, 'moved': {'kind': kind, 'at': at},
                            **({'review_observation': {'head_sha': A, 'at': at, 'event_ids': []}}
                               if stage == 'reviewing' else {}),
                            **({'done_at': at} if stage == 'removed' else {}),
                            **({'snoozed_until': ahead(**extra['snoozed']),
                                'snooze_baseline': {'head_sha': A, 'event_ids': []}} if 'snoozed' in extra else {})}
    queue.save(data)
    dashboard.save_dashboard({'prs': {}, 'last_github_refresh_at': now})


def main():
    with tempfile.TemporaryDirectory(prefix='my-reviews-browser-') as root:
        os.environ['PR_REVIEW_TRACKER_HOME'] = root
        os.environ['PR_REVIEW_TRACKER_GH'] = '/usr/bin/false'
        import dashboard_queue as queue
        import dashboard_reporting as reporting
        import dashboard_runtime as runtime
        import dashboard_triage as triage
        import pr_dashboard as dashboard
        import pr_server as server_module
        signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
        triage.configure({'enabled': False})
        seed(queue, dashboard)
        disabled = ValueError('Fixture: disabled.')
        with patch.object(dashboard, 'discover_claude_options', return_value=([''], [''])), \
             patch.object(queue, 'start_refresh', return_value=False), \
             patch.object(runtime, 'start_refresh', return_value=False), \
             patch.object(runtime, 'start_launch', side_effect=disabled), \
             patch.object(triage, 'start', return_value=False), \
             patch.object(reporting, 'start_refresh', return_value=False):
            server = server_module.Server(('127.0.0.1', 0))
            print(f'http://127.0.0.1:{server.server_port}', flush=True)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
            finally:
                server.server_close()


if __name__ == '__main__':
    main()

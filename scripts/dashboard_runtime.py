"""Local dashboard state, artifact history, and durable launches."""
from __future__ import annotations
from argparse import Namespace
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import threading
import pr_dashboard as dashboard
import pr_review_tracker as tracker
import dashboard_queue as queue
import dashboard_reviews as reviews
import ai_cost
import ai_settings
import review_update
import review_verdict
import workspace_context as selected_workspace_context
from agent_options import CATALOG

ARTIFACT_NAMES = ('review-html', 'explanation-html', 'review-markdown')
TERMINAL = {'completed', 'completed-with-gaps', 'failed', 'blocked', 'cancelled'}
LEGACY_RUN_STALE_SECONDS = 60 * 60


def artifact_allowed(path):
    try:
        path = Path(path).resolve(strict=True)
        return path.is_file() and any(path.is_relative_to(root) for root in (
            tracker.tracker_root().resolve(), dashboard.explainer_output_root()))
    except (OSError, ValueError):
        return False


def artifact_version(artifact):
    # Legacy registrations have no version ID. Keep a stable identity until
    # they are registered again, including replacements at the same path.
    return artifact.get('version') or hashlib.sha256(
        json.dumps(artifact, sort_keys=True).encode()).hexdigest()


def registered_report(path=None, version=None, pr_url=None):
    """Find the review report registration for a served path or a version ID."""
    try:
        path = Path(path).resolve(strict=True) if path else None
    except (OSError, ValueError):
        return None
    runs, _ = tracker.load_all_runs(dashboard.STALE_RUN_HOURS)
    for run in sorted(runs, key=lambda r: r.get('created_at', ''), reverse=True):
        if pr_url and run.get('pr_url') != pr_url:
            continue
        for artifact in run.get('artifacts', []):
            if artifact.get('name') not in ('review-html', 'review-markdown'):
                continue
            if version and artifact_version(artifact) != version:
                continue
            try:
                if path and Path(artifact.get('path', '')).resolve() != path:
                    continue
            except (OSError, ValueError):
                continue
            return {'run_id': run['run_id'], 'name': artifact['name'], 'version': artifact_version(artifact),
                    'head_sha': artifact.get('head_sha', run.get('head_sha', ''))}
    return None


def mark_artifact_opened(run_id, name, version):
    if name not in ARTIFACT_NAMES or not isinstance(version, str) or not version:
        raise dashboard.DashboardError('Unknown artifact version.')
    with dashboard.state_lock():
        directory = tracker.run_dir(run_id)
        tracker.read_json(directory / 'run.json')
        artifact = tracker.read_json(directory / 'artifacts' / f'{name}.json', required=False)
        if not artifact or artifact_version(artifact) != version or not artifact_allowed(artifact.get('path', '')):
            # An old tab must never acknowledge a replacement it did not open.
            return {'opened': False}
        path = directory / 'artifact-views.json'
        views = tracker.read_json(path, required=False)
        views[name] = version
        tracker.atomic_write(path, views)
    return {'opened': True}


def report_verdict(path, head):
    """The renderer's verdict sidecar for a report, if it matches that report's head."""
    try:
        value = json.loads(Path(path).with_name('review-verdict.json').read_text())
    except (OSError, ValueError):
        return None
    if (not isinstance(value, dict) or (head and value.get('head') != head)
            or value.get('kind') not in review_verdict.KINDS or value.get('tone') not in review_verdict.TONES
            or value.get('confidence') not in ('high', 'medium', 'low', None)):
        return None
    return {'short': review_verdict.SHORT[value['kind']], 'tone': value['tone'],
            'headline': str(value.get('headline', '')), 'confidence': value['confidence']}


def collect_artifacts(runs, checked_sha=''):
    """Prefer completed artifacts, even while other tasks are still running."""
    candidates = []
    ordered = sorted(runs, key=lambda r:r.get('created_at', ''), reverse=True)
    for run in ordered:
        views = tracker.read_json(tracker.run_dir(run['run_id']) / 'artifact-views.json', required=False)
        tasks = {task['task']: task['status'] for task in run.get('tasks', [])}
        for artifact in run.get('artifacts', []):
            name, path = artifact.get('name'), artifact.get('path', '')
            if name not in ARTIFACT_NAMES or not artifact_allowed(path):
                continue
            task = {'review-html':'report', 'explanation-html':'explainer', 'review-markdown':'drafts'}[name]
            ready = run.get('status') == 'completed' or tasks.get(task) == 'completed'
            head = artifact.get('head_sha', run.get('head_sha', ''))
            version = artifact_version(artifact)
            candidates.append((ready, {'name': name, 'path': path, 'run_id': run['run_id'],
                'version': version, 'unread': views.get(name) != version,
                'freshness': 'unknown' if not head or not checked_sha else ('current' if head == checked_sha else 'older'),
                'created_at': artifact.get('updated_at') or run.get('created_at', ''), 'head_sha': head,
                'status': 'completed' if ready else run.get('status'), 'tool': run.get('tool', ''),
                **({'verdict': report_verdict(path, head)} if name == 'review-html' and ready else {})}))
    chosen = {}
    # Partial results only fill missing artifact types. A new unfinished
    # explainer must not hide the previous finished explanation.
    for _, artifact in sorted(candidates, key=lambda item: not item[0]):
        chosen.setdefault(artifact['name'], artifact)
    if 'review-html' in chosen:
        combined = chosen['review-html']
        if combined['status'] == 'completed' or not any(a['status'] == 'completed' for name, a in chosen.items() if name != 'review-html'):
            return {'review-html': combined}
        del chosen['review-html']
    return chosen


def launch_path(run_id):
    return tracker.run_dir(run_id) / 'dashboard-launch.json'


def age_seconds(stamp):
    try:
        return (datetime.now(timezone.utc) - tracker.parse_time(stamp)).total_seconds()
    except (ValueError, TypeError):
        return 0


def summarize_run(run, checked_sha=''):
    launch = tracker.read_json(launch_path(run['run_id']), required=False)
    status = run['status']
    if launch.get('exit_code') is not None and status not in TERMINAL:
        status = 'failed'
    elif status == 'queued':
        status = 'starting' if age_seconds(run['created_at']) < 180 else 'no-activity'
    elif status == 'potentially-stale':
        status = 'no-activity'
    job = reviews.job_state(run['run_id'])
    if job:
        status = job['status']
    elif status == 'running' and age_seconds(run.get('updated_at', '')) > LEGACY_RUN_STALE_SECONDS:
        # Legacy sessions have no local worker to report liveness. Do not leave a
        # dead terminal session blocking a new review indefinitely.
        status = 'no-activity'
    return {'run_id': run['run_id'], 'status': status, 'tool': run.get('tool', ''),
        'created_at': run.get('created_at', ''), 'updated_at': run.get('updated_at', ''),
        'head_sha': run.get('head_sha', ''), 'session_reference': run.get('session_reference', ''),
        'kind': launch.get('kind', 'review'), 'mode': launch.get('mode', 'full'), 'guidance': launch.get('guidance', ''), 'workspace_context': launch.get('workspace_context', {}), 'transport': 'in-app' if job or launch.get('transport') in ('codex-sdk', 'in-app') else 'legacy',
        'progress': reviews.progress(run, status) if job else None, 'cost': ai_cost.for_run(run['run_id']) if job else None,
        'message': job.get('message', '') or launch.get('message', '') or run.get('control', {}).get('message', ''),
        'tasks': [{'name': t['task'], 'status': t['status'], 'message': t.get('message', '')} for t in run.get('tasks', [])],
        'artifacts': collect_artifacts([run], checked_sha)}


def snapshot():
    with dashboard.state_lock():
        data = dashboard.load_dashboard()
        config = dashboard.load_config()
        ai = ai_settings.load()
        personal = queue.load()
        entries = queue.merged_entries(data['prs'], personal)
    import dashboard_triage
    runs, errors = tracker.load_all_runs(dashboard.STALE_RUN_HOURS)
    triage = dashboard_triage.snapshot(entries, runs)
    grouped = {}
    for run in runs:
        grouped.setdefault(run['pr_url'], []).append(run)
    prs = []
    for url, entry in entries.items():
        history = grouped.get(url, [])
        checked_sha = entry.get('head_sha', '')
        artifacts = collect_artifacts(history, checked_sha)
        reasons = entry.get('reasons', [])
        group = 'mine' if 'author' in reasons else ('requested' if any(r in reasons for r in ('review-requested', 'assignee')) else 'watching')
        state = entry.get('my_review_state', '')
        participation = {'APPROVED':'Approved', 'CHANGES_REQUESTED':'Changes requested',
            'COMMENTED':'Commented in review', 'DISMISSED':'Review dismissed'}.get(state, '')
        if not participation:
            participation = 'Commented' if entry.get('my_comment_at') else (
                'Previous activity · refresh to classify' if entry.get('reviewed_by_me_at') and 'my_review_state' not in entry else 'Not reviewed')
        freshness = 'unknown'
        if artifacts and checked_sha:
            heads = [a['head_sha'] for a in artifacts.values()]
            if any(head and head != checked_sha for head in heads):
                freshness = 'older'
            elif all(heads):
                freshness = 'current'
        mixed = len({a['run_id'] for a in artifacts.values()}) > 1
        login = dashboard.normalize_author_login(entry.get('author_login', ''))
        profile = data.get('author_profiles', {}).get(login, {})
        prs.append({**entry, 'author_login': login, 'author_name': profile.get('author_name', ''),
                    'author_avatar_url': profile.get('author_avatar_url', ''), 'url': url, 'group':group, 'participation':participation,
            'triage':triage['prs'].get(url, {}), 'update_check':triage['updates'].get(url), 'artifacts':artifacts, 'artifact_freshness':freshness, 'mixed_artifacts':mixed,
            'run':summarize_run(history[0], checked_sha) if history else None,
            'history':[summarize_run(r, checked_sha) for r in history],
            'history_total':len(history)})
    return {'prs':prs, 'config':config, 'ai': {'settings': ai, 'revision': ai_settings.revision(ai), 'catalog': CATALOG}, 'triage': {k: v for k, v in triage.items() if k not in ('prs', 'updates')}, 'queue_refresh':queue.status(),
        'last_github_refresh_at':data.get('last_github_refresh_at', ''),
        'last_refresh_attempt_at':data.get('last_refresh_attempt_at', ''),
        'warnings':data.get('refresh_warnings', []) + errors,
        'refresh':tracker.read_json(tracker.tracker_root()/'dashboard-refresh.json',required=False),
        'models':{'claude':dashboard.discover_claude_options()[0], 'codex':dashboard.CODEX_MODELS},
        'efforts':{'claude':dashboard.discover_claude_options()[1], 'codex':dashboard.CODEX_EFFORTS},
        'model_efforts': {'codex': dashboard.CODEX_MODEL_EFFORTS}}


GUIDANCE_LIMIT = 2000
DEEP_EXPLANATION = 'Write an in-depth (Deep) explanation, per references/explanation.md.'


def review_guidance(value):
    guidance = value.strip() if isinstance(value, str) else ''
    if len(guidance) > GUIDANCE_LIMIT:
        raise dashboard.DashboardError(f'Keep review guidance under {GUIDANCE_LIMIT} characters.')
    return guidance


def guidance_prompt(guidance):
    if not guidance:
        return ''
    # Guidance steers scope and validation; the skill's publishing and safety rules still apply.
    return ('\n\nReviewer guidance for this run, written by the person requesting the review:\n'
        f'<<<\n{guidance}\n>>>\n'
        'Follow this guidance when choosing scope, reviewers, validation and effort. '
        'It does not override the rules against publishing to GitHub or exposing secrets. '
        'Still report any serious defect you notice outside that scope. '
        'Say in the report which guidance was applied and which checks it skipped.')


def active_runs(canonical, runs):
    active = {'starting', 'queued', 'running', 'stopping'}
    return [r for r in runs if r['pr_url'] == canonical and
            (summarize_run(r)['status'] in active or
             (reviews.read_job(r['run_id']) and reviews.worker_alive(r['run_id'])))]


def previous_review(canonical, entry, mode):
    """The review to build on and the fixed-rule check; network reads happen outside the state lock."""
    runs, _ = tracker.load_all_runs(dashboard.STALE_RUN_HOURS)
    if active_runs(canonical, runs):
        return None, None
    prior = review_update.prior_reviews([r for r in runs if r['pr_url'] == canonical]).get(canonical)
    if not prior:
        if mode == 'update':
            raise dashboard.DashboardError('There is no finished AI review to update. Run a full AI review.')
        return None, None
    if prior['head'] == entry.get('head_sha') and mode == 'full':
        return prior, {'eligible': False, 'reason': 'The last AI review already covers the latest commit.'}
    try:
        check = review_update.gate(canonical, prior, entry.get('head_sha', ''), entry.get('base_sha', ''))
    except (OSError, ValueError, review_update.UpdateError):
        check = {'eligible': False, 'reason': 'The commits since the last AI review could not be checked.'}
    if mode == 'update' and not check['eligible']:
        raise dashboard.DashboardError(check['reason'] + ' Run a full AI review instead.')
    return prior, check


def start_launch(url, kind, retry=False, guidance='', mode='full', workspace_context=None, deep_explanation=False):
    canonical, *_ = tracker.canonical_pr_url(url)
    guidance = review_guidance(guidance)
    if deep_explanation:
        # Kept in the guidance text, so the run shows what was asked for.
        guidance = (guidance + '\n' if guidance else '') + DEEP_EXPLANATION
    if kind not in ('review', 'explainer'):
        raise dashboard.DashboardError('Unknown review action.')
    if mode not in ('full', 'update'):
        raise dashboard.DashboardError('Choose a full review or an update.')
    # Old open tabs may still send the retired action; perform a full review.
    kind = 'review'
    with dashboard.state_lock():
        entry = queue.merged_entries(dashboard.load_dashboard()['prs']).get(canonical)
        if entry is None:
            raise dashboard.DashboardError('This PR is no longer in the inbox. Refresh the page.')
    prior, check = previous_review(canonical, entry, mode)
    with dashboard.state_lock():
        entry = queue.merged_entries(dashboard.load_dashboard()['prs']).get(canonical)
        if entry is None:
            raise dashboard.DashboardError('This PR is no longer in the inbox. Refresh the page.')
        runs, errors = tracker.load_all_runs(dashboard.STALE_RUN_HOURS)
        active = active_runs(canonical, runs)
        if active and not retry:
            return {'run_id': active[0]['run_id'], 'existing': True,
                    'transport': summarize_run(active[0])['transport']}
        if mode == 'update' and (not prior or prior['head'] == entry.get('head_sha')):
            raise dashboard.DashboardError('The PR changed while checking it. Try again.')
        private_context_prompt, private_context_meta = selected_workspace_context.build(
            canonical, workspace_context, current_head=entry.get('head_sha', ''))
        if active and retry:
            for run in active:
                if reviews.read_job(run['run_id']):
                    raise dashboard.DashboardError('Stop the active AI review and wait for it to finish before retrying.')
                tracker.command_cancel(Namespace(run_id=run['run_id'], message='Tracking released for an explicit retry; legacy process is not terminated.'))
        config = ai_settings.selected('review')
        run_id = tracker.command_start(Namespace(pr_url=canonical,
            tool=CATALOG[config['provider']]['tracker_tool'],
            title=entry.get('title',''), working_directory=str(tracker.tracker_root()),
            session_reference='', base_sha='', head_sha=''), emit=False)
        transport = 'in-app'
        meta = {'kind':kind, 'mode':mode, 'agent':config['provider'], 'transport':transport, 'created_at':tracker.utc_now(), 'message':''}
        if guidance:
            meta['guidance'] = guidance
        if private_context_meta:
            meta['workspace_context'] = private_context_meta
        if prior:
            meta.update(previous_run=prior['run_id'], update_chain=prior['chain'] + 1 if mode == 'update' else 0)
            precheck = None
            if mode == 'update':
                import dashboard_triage
                precheck = dashboard_triage.update_view(canonical, entry, prior)
            tracker.atomic_write(tracker.run_dir(run_id) / review_update.CONTEXT_FILE, review_update.update_context(
                canonical, prior, entry.get('head_sha', ''), (check or {}).get('merge_base', ''), mode, check, precheck))
            # Only runs with a previous review show this stage.
            tracker.command_set_task(Namespace(run_id=run_id, task='previous-findings', status='queued', message=''))
        tracker.atomic_write(launch_path(run_id), meta)
        prompt = (dashboard.update_review_prompt if mode == 'update' else dashboard.full_review_prompt)(canonical)
        if prior and mode == 'full':
            prompt += dashboard.previous_review_note(tracker.run_dir(run_id) / review_update.CONTEXT_FILE)
        prompt += ('\n\nThe dashboard has already registered this exact run. '
            f'Use run ID {run_id} for every tracker command; do not create another run. '
            'Read the installed skill instructions before proceeding. '
            'Update checkout, explanation, review, and report tasks as you work. '
            'Record a session reference when available; otherwise leave it blank without asking. '
            'This request authorizes the complete local review workflow and its local artifacts, '
            'not posting anything to GitHub.')
        prompt += guidance_prompt(guidance)
        prompt += private_context_prompt
        try:
            reviews.start(run_id, prompt, config)
        except (OSError, dashboard.DashboardError) as error:
            record_launch_failure(run_id, str(error))
            raise dashboard.DashboardError(str(error)) from error
    if kind == 'review' and not entry.get('workflow'):
        queue.mutate(canonical, 'enqueue')
    return {'run_id':run_id, 'existing':False, 'transport':transport, 'mode':mode}


def record_launch_failure(run_id, message):
    meta = tracker.read_json(launch_path(run_id), required=False)
    meta.update(exit_code=1, exited_at=tracker.utc_now(), message=message)
    reviews.finish_unfinished_tasks(run_id, 'failed', message)
    tracker.atomic_write(launch_path(run_id), meta)


_refresh_guard = threading.Lock()


def start_refresh():
    if not _refresh_guard.acquire(blocking=False):
        return False
    status_path = tracker.tracker_root()/'dashboard-refresh.json'
    tracker.atomic_write(status_path, {'status':'running','started_at':tracker.utc_now()})
    def worker():
        try:
            dashboard.command_refresh(Namespace())
            tracker.atomic_write(status_path, {'status':'completed','finished_at':tracker.utc_now()})
        except Exception as error:
            tracker.atomic_write(status_path, {'status':'failed','finished_at':tracker.utc_now(),'message':str(error)})
        finally:
            _refresh_guard.release()
    threading.Thread(target=worker,daemon=True).start()
    return True

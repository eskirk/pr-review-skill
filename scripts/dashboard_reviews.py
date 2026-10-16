"""Launch and supervise durable in-app reviews independently of HTTP requests."""
from __future__ import annotations
from argparse import Namespace
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

import ai_cost
import ai_runtime
import pr_discussion
import report_check
import storage_cleanup
from review_context import WRAP_UP_PROMPT, message_prompt, review_prompt, style_skill_for_job
import pr_review_tracker as tracker
from review_jobs import (
    Activity, FINAL, complete_report, events, finish_unfinished_tasks,
    job_state, path, progress, read_job, snapshot, worker_alive, worker_lock,
)

CANCEL_GRACE_SECONDS = 8
HEARTBEAT_SECONDS = 10
MESSAGE_LIMIT = 2000
WRAPPED_UP = 'Wrapped up early; review notes cover the evidence gathered so far.'


def start(run_id, prompt, config):
    """Spawn a dedicated session so cancellation cannot target other reviews."""
    style = style_skill_for_job()
    job = {
        'status': 'starting',
        'created_at': tracker.utc_now(),
        'updated_at': tracker.utc_now(),
        'message': 'Starting AI review',
        'provider': config.get('provider', config.get('agent', 'codex')),
        'model': config['model'],
        'effort': config['effort'],
        'prompt': prompt,
        # Store source metadata, not the private style file contents. The worker
        # reloads this exact path before building the provider prompt.
        'style_skill': style['metadata'],
    }
    tracker.atomic_write(path(run_id), job)
    python = os.environ.get('PR_REVIEW_PYTHON') or sys.executable
    try:
        process = subprocess.Popen(
            [python, str(Path(__file__).resolve()), 'worker', run_id],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=tracker.tracker_root(),
            env={**os.environ, 'PR_REVIEW_TRACKER_HOME': str(tracker.tracker_root())},
            start_new_session=True,
        )
    except OSError:
        Activity(run_id, job).state('failed', 'Could not start the AI worker.')
        raise
    threading.Thread(target=process.wait, daemon=True).start()


def cancel(run_id):
    job = job_state(run_id)
    if not job:
        raise tracker.TrackerError('This is not an in-app AI review.')
    if job['status'] in FINAL:
        return {'status': job['status']}
    tracker.atomic_write(path(run_id, 'review-cancel.json'), {
        'requested_at': tracker.utc_now(),
    })
    return {'status': 'stopping'}


def send_message(run_id, text, wrap_up=False):
    """Queue a question, steer or wrap-up request for the worker to deliver."""
    job = job_state(run_id)
    if not job:
        raise tracker.TrackerError('This is not an in-app AI review.')
    if job['status'] in FINAL or job['status'] == 'stopping':
        raise tracker.TrackerError('This review is no longer running.')
    text = text.strip() if isinstance(text, str) else ''
    if len(text) > MESSAGE_LIMIT:
        raise tracker.TrackerError(f'Keep messages under {MESSAGE_LIMIT} characters.')
    if not text and not wrap_up:
        raise tracker.TrackerError('Write a message first.')
    if wrap_up and job.get('wrap_up_requested_at'):
        return {'status': 'wrapping-up'}
    record = {'at': tracker.utc_now(), 'text': text, 'wrap_up': bool(wrap_up)}
    target = path(run_id, 'review-inbox.jsonl')
    with os.fdopen(os.open(target, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600), 'a') as handle:
        handle.write(json.dumps(record) + '\n')
    return {'status': 'queued'}


class ReviewWorker:
    """Own one SDK client, activity writer, and cancellation watcher."""

    def __init__(self, run_id, job, client_factory, discussion=pr_discussion.save):
        self.run_id = run_id
        self.discussion = discussion
        self.activity = Activity(run_id, job)
        self.client_factory = client_factory
        self.client = None
        self.thread_id = None
        self.turn_id = None
        self.cost = None
        self.stopped = threading.Event()
        self.cancel_requested = threading.Event()
        self.needs_input = threading.Event()
        self.inbox_offset = 0
        # The reviewer's sandbox cannot launch Chrome; this worker renders and checks the report for it.
        self.report_check = report_check.Service(run_id)

    def event(self, kind, text):
        if kind == 'attention':
            self.needs_input.set()
        self.activity.emit(kind, text)

    def interrupt(self):
        if self.client:
            try:
                self.client.interrupt()
            except Exception:
                pass  # Dedicated process-group timeout handles a stalled adapter.

    def deliver_messages(self):
        """Forward queued dashboard messages once the provider session can take them."""
        inbox = path(self.run_id, 'review-inbox.jsonl')
        if not self.client or not inbox.exists():
            return
        with inbox.open('rb') as handle:
            handle.seek(self.inbox_offset)
            pending = handle.read()
        while b'\n' in pending:
            line, pending = pending.split(b'\n', 1)
            try:
                message = json.loads(line)
            except (ValueError, UnicodeDecodeError):
                self.inbox_offset += len(line) + 1
                continue
            steer = getattr(self.client, 'steer', None)
            if not steer:
                self.inbox_offset += len(line) + 1
                self.activity.emit('attention', 'This provider cannot take messages during a review.')
                continue
            wrap_up = message.get('wrap_up') is True
            text = str(message.get('text', ''))[:MESSAGE_LIMIT]
            prompt = WRAP_UP_PROMPT + (f'\n\nTheir note:\n<<<\n{text}\n>>>' if text else '') if wrap_up else message_prompt(text)
            try:
                if not steer(prompt, wrap_up=wrap_up):
                    return  # Session not ready yet; retry on the next tick.
            except Exception as error:
                self.inbox_offset += len(line) + 1
                self.activity.emit('attention', f'Could not deliver the message ({type(error).__name__}).')
                continue
            self.inbox_offset += len(line) + 1
            if wrap_up:
                self.activity.state(message='Wrapping up with the evidence gathered so far…',
                                    wrap_up_requested_at=tracker.utc_now())
            self.activity.emit('you', ('Wrap up now. ' + text).strip() if wrap_up else text)

    def mark_cancelled(self):
        tracker.command_cancel(Namespace(
            run_id=self.run_id, message='Review cancelled from the dashboard.'))
        self.activity.state('cancelled', 'Review cancelled. Partial activity retained.')

    def monitor(self):
        heartbeat = time.monotonic()
        while not self.stopped.wait(1):
            if path(self.run_id, 'review-cancel.json').exists():
                self.cancel_requested.set()
                self.activity.state('stopping', 'Stopping AI…')
                threading.Thread(target=self.interrupt, daemon=True).start()
                if not self.stopped.wait(CANCEL_GRACE_SECONDS):
                    self.mark_cancelled()
                    # Only the dedicated session created by start() is eligible.
                    if os.getpid() == os.getpgrp():
                        os.killpg(os.getpgrp(), signal.SIGKILL)
                return
            try:
                self.deliver_messages()
            except OSError:
                pass  # The inbox is retried on the next tick.
            try:
                self.report_check.poll()
            except (OSError, tracker.TrackerError):
                pass  # The request is retried on the next tick.
            if time.monotonic() - heartbeat >= HEARTBEAT_SECONDS:
                self.activity.heartbeat()
                heartbeat = time.monotonic()

    def finish_turn(self, payload):
        if payload.get('turn', {}).get('status') != 'completed':
            self.activity.state('failed',
                'AI stopped before completing the review. Saved activity is available.')
            return
        if complete_report(self.run_id):
            tasks = tracker.load_run(tracker.run_dir(self.run_id), 6)['tasks']
            gaps = any(task['status'] in ('blocked', 'failed', 'cancelled') for task in tasks)
            if self.activity.job.get('wrap_up_requested_at'):
                self.activity.state('completed-with-gaps', WRAPPED_UP)
                return
            self.activity.state(
                'completed-with-gaps' if gaps else 'completed',
                'Review notes are ready; some checks could not be completed.'
                if gaps else 'Review notes are ready.',
            )
            return
        self.activity.state(
            'blocked' if self.needs_input.is_set() else 'failed',
            'Review needs input.' if self.needs_input.is_set() else
            'AI finished without registering a complete report. Check the saved activity.',
        )

    def review(self):
        self.client = self.client_factory()
        job = self.activity.job
        style = style_skill_for_job(job)
        if style['metadata'] != job.get('style_skill'):
            self.activity.state(style_skill=style['metadata'])
            job = self.activity.job
        def session(session_id):
            tracker.command_set_session(Namespace(run_id=self.run_id, reference=session_id))
            self.activity.state('running', 'Review in progress', thread_id=session_id)
        self.save_discussion()
        self.activity.state('running', 'Connecting to the selected provider…')
        result = self.client.run(ai_runtime.Request(
            mode='review', cwd=str(tracker.tracker_root()),
            prompt=review_prompt(self.run_id, job['prompt'], job, style=style),
            model=job.get('model', ''), effort=job.get('effort', ''),
        ), ai_runtime.Callbacks(emit=self.event, session=session))
        self.cost = result.get('cost')
        if not self.cancel_requested.is_set():
            self.finish_turn({'turn': {'status': 'completed' if result.get('completed') else 'failed'}})

    def record_cost(self):
        """Price the finished run; failed or stopped Claude runs still leave a transcript total."""
        job = self.activity.job
        try:
            cost = self.cost
            if not cost and job.get('provider') == 'claude':
                cost = ai_cost.claude_transcript_cost(job.get('thread_id', ''))
            if cost:
                ai_cost.record(self.run_id, job, cost, 'live')
        except Exception:
            pass  # Cost is informational; the dashboard backfill retries missing runs.

    def save_discussion(self):
        """Give every reviewer the same PR discussion; the skill falls back to gh if this fails."""
        self.activity.state('running', 'Reading PR discussion…')
        try:
            _, note = self.discussion(self.run_id)
            self.activity.emit('update', f'Saved the PR discussion: {note}.')
        except Exception as error:
            # Messages may echo GitHub output; record only the type.
            self.activity.emit('update', f'Could not save the PR discussion ({type(error).__name__}); '
                               'the reviewer will read it from GitHub.')

    def run(self):
        watcher = threading.Thread(target=self.monitor, daemon=True)
        watcher.start()
        try:
            if path(self.run_id, 'review-cancel.json').exists():
                self.cancel_requested.set()
            else:
                self.review()
        except Exception as error:
            # Provider exceptions may contain source or credentials; save only type.
            name = type(error).__name__
            self.activity.emit('error', f'AI worker error ({name}).')
            self.activity.state('failed',
                str(error) if isinstance(error, ai_runtime.ProviderError) else f'AI could not finish ({name}). Check provider authentication and the installed SDK.')
        finally:
            try:
                if self.client:
                    self.client.close()
            finally:
                self.stopped.set()
                watcher.join(timeout=2)
                if self.cancel_requested.is_set():
                    self.mark_cancelled()
                job = self.activity.job
                finish_unfinished_tasks(self.run_id, job['status'], job.get('message', ''))
                self.activity.emit('status', job.get('message', 'Review ended.'))
                self.record_cost()
                try:
                    # The report is final; build caches and check screenshots are no longer needed.
                    storage_cleanup.prune_run(tracker.run_dir(self.run_id))
                except OSError:
                    pass


def run_worker(run_id, client_factory=None):
    with worker_lock(run_id):
        job = read_job(run_id)
        if job and job['status'] not in FINAL:
            ReviewWorker(run_id, job, client_factory or (lambda: ai_runtime.create(job.get('provider', 'codex')))).run()


if __name__ == '__main__':
    if len(sys.argv) != 3 or sys.argv[1] != 'worker':
        raise SystemExit('Usage: dashboard_reviews.py worker RUN_ID')
    run_worker(sys.argv[2])

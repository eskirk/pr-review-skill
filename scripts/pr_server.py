#!/usr/bin/env python3
"""Loopback PR inbox with authenticated local actions and isolated artifacts."""
from __future__ import annotations
import argparse
import html
import json
import mimetypes
import secrets
import re
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse, unquote, quote

sys.path.insert(0,str(Path(__file__).resolve().parent))
import pr_dashboard as dashboard
import pr_review_tracker as tracker
import dashboard_runtime as runtime
import ai_cost
import dashboard_reporting as reporting
import dashboard_queue as queue
import dashboard_triage as triage
import ai_settings
import dashboard_reviews as reviews
import code_workspace as workspace
import workspace_github
import workspace_chat
import workspace_comments
import workspace_report
import workspace_progress
import workspace_context

ASSETS = Path(__file__).resolve().parent.parent / 'assets'
MUTATIONS = {'/ai-config','/triage-config','/triage-feedback','/triage-run','/triage-reestimate','/artifact-opened','/queue','/refresh-queue','/recover-reviews','/refresh-reporting','/refresh','/hide','/unhide','/snooze','/unsnooze','/set-config',
             '/add-repo','/remove-repo','/add-host-repo','/remove-host-repo','/regenerate-review','/regenerate-explainer','/copy-prompt','/review-cancel','/review-message','/workspace-save','/workspace-chat','/workspace-chat-cancel','/workspace-comment'}


class Server(ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, address, handler=None):
        super().__init__(address, handler or Handler)
        self.csrf_token = secrets.token_urlsafe(32)


class Handler(BaseHTTPRequestHandler):
    server_version = 'PRDashboard/2'
    def log_message(self, *args):
        pass

    def _send(self, code, body, content_type='application/json; charset=utf-8', csp=None, cache='no-store'):
        if isinstance(body, dict):
            body = json.dumps(body).encode()
        elif isinstance(body,str):
            body = body.encode()
        self.send_response(code)
        self.send_header('Content-Type',content_type)
        self.send_header('Content-Length',str(len(body)))
        self.send_header('Cache-Control',cache)
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Content-Security-Policy',csp or "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: https://github.com https://avatars.githubusercontent.com; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        self.end_headers()
        self.wfile.write(body)

    def _error(self,code,message):
        self._send(code,{'error':message})

    def _valid_host(self):
        port = self.server.server_port
        return self.headers.get('Host') in (f'127.0.0.1:{port}',f'localhost:{port}')

    def _valid_origin(self):
        origin = self.headers.get('Origin')
        return origin == 'http://' + self.headers.get('Host','')

    def _serve_artifact(self, query, embedded=False):
        raw = (parse_qs(query).get('path') or [''])[0]
        if not raw:
            self._error(400,'Missing artifact path.'); return
        if not runtime.artifact_allowed(raw):
            self._error(404,'This artifact is missing or outside the review folders.'); return
        path=Path(raw).resolve()
        suffix=path.suffix.lower()
        if suffix == '.md':
            body=dashboard.render_markdown_page(path.name,path,dashboard.markdown_to_html(path.read_text()))
            body = workspace_report.embed(body) if embedded else workspace_report.standalone(body)
            # Markdown is sanitized by our renderer; permit its fixed copy handler.
            self._send(200,body,'text/html; charset=utf-8',
                ("sandbox allow-scripts; default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'none'; frame-ancestors FRAME; base-uri 'none'; form-action 'none'").replace("FRAME", "'self'" if embedded else "'none'"))
        elif suffix in ('.html','.htm'):
            # Opaque sandbox origin: explainer scripts can run, but cannot read
            # dashboard state/tokens or send authenticated dashboard actions.
            def local_link(match):
                raw = html.unescape(match.group(2))
                parsed = urlparse(raw)
                if parsed.netloc not in ('', 'localhost'):
                    return match.group(0)
                target = unquote(parsed.path)
                if not runtime.artifact_allowed(target):
                    return match.group(0)
                return 'href=' + match.group(1) + '/artifact?path=' + quote(target, safe='') + match.group(1)
            body = re.sub(r"href=([\"'])(file://[^\"']+)\1", local_link, path.read_text())
            body = workspace_report.embed(body) if embedded else workspace_report.standalone(body)
            self._send(200,body,'text/html; charset=utf-8',
                ("sandbox allow-scripts allow-popups allow-popups-to-escape-sandbox; default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src data: https:; font-src data:; connect-src 'none'; frame-ancestors FRAME; base-uri 'none'; form-action 'none'").replace('FRAME', "'self'" if embedded else "'none'"))
        elif suffix in ('.png','.jpg','.jpeg','.webp','.gif'):
            self._send(200,path.read_bytes(),mimetypes.guess_type(str(path))[0])
        else:
            self._send(200,path.read_bytes(),'text/plain; charset=utf-8',"sandbox; default-src 'none'")

    def _review_events(self, run_id):
        current = reviews.snapshot(run_id)  # Validate before sending headers.
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        previous = None
        try:
            # Reconnects replay a bounded saved activity window, even after server restart.
            # The worker is independent of this connection and HTTP server.
            for _ in range(60):
                encoded = json.dumps(current)
                if encoded != previous:
                    self.wfile.write(('event: review\ndata: ' + encoded + '\n\n').encode())
                    previous = encoded
                else:
                    self.wfile.write(b': heartbeat\n\n')
                self.wfile.flush()
                if current['status'] in reviews.FINAL:
                    return
                time.sleep(1)
                current = reviews.snapshot(run_id)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        if not self._valid_host():
            self._error(403,'Unexpected host.'); return
        parsed=urlparse(self.path)
        try:
            if parsed.path in MUTATIONS:
                self._error(405,'Use the dashboard action button to make a POST request.')
            elif parsed.path == '/workspace':
                page=(ASSETS/'code-workspace/index.html').read_text().replace('__CSRF_TOKEN__',html.escape(self.server.csrf_token,quote=True))
                self._send(200,page,'text/html; charset=utf-8')
            elif parsed.path.startswith('/assets/code-workspace/'):
                name = parsed.path.removeprefix('/assets/code-workspace/')
                if name not in ('workspace.js','workspace.css','model.mjs','api.mjs','diff.mjs','review.mjs','views.mjs','progress.mjs','chat-markdown.mjs','chat-resize.mjs','comments.mjs','vendor/markdown-it.mjs'):
                    self._error(404,'Asset not found.'); return
                self._send(200,(ASSETS/'code-workspace'/name).read_bytes(), 'text/css' if name.endswith('.css') else 'text/javascript')
            elif parsed.path.startswith('/api/workspace') or parsed.path == '/workspace-report':
                if self.headers.get('Sec-Fetch-Site') == 'cross-site' or (self.headers.get('Origin') and not self._valid_origin()):
                    self._error(403,'Workspace data is only available from this origin.'); return
                query=parse_qs(parsed.query)
                url=query.get('url',[''])[0]
                rev=query.get('revision',[None])[0]
                if parsed.path == '/api/workspace':
                    load_id=query.get('load',[''])[0]
                    try:
                        self._send(200,workspace.load(url,rev,workspace_progress.reporter(load_id)))
                    finally:
                        workspace_progress.finish(load_id)
                elif parsed.path == '/api/workspace-progress':
                    self._send(200,workspace_progress.snapshot(query.get('load',[''])[0]))
                elif parsed.path == '/api/workspace-file':
                    self._send(200,workspace_github.file_diff(url,rev,query.get('path',[''])[0]))
                elif parsed.path == '/api/workspace-comments':
                    self._send(200,workspace_comments.load(url,query.get('refresh',[''])[0] == '1'))
                elif parsed.path == '/api/workspace-chat':
                    self._send(200,workspace_chat.snapshot(url,query.get('thread_id',[''])[0]))
                elif parsed.path == '/api/workspace-context':
                    self._send(200,workspace_context.summaries(url,query.get('head',[''])[0]))
                elif parsed.path == '/api/workspace-ai':
                    self._send(200, ai_settings.selected('chat'))
                elif parsed.path == '/api/workspace-review':
                    self._send(200,workspace.review(url,query.get('head',[''])[0]))
                elif parsed.path == '/api/workspace-finding':
                    self._send(200,workspace.finding(url,rev,query.get('version',[''])[0],query.get('finding',[''])[0]))
                elif parsed.path == '/workspace-report':
                    info=workspace.review(url,query.get('head',[''])[0])
                    artifact=info['artifact']
                    if not artifact or artifact['version'] != query.get('version',[''])[0]:
                        self._error(404,'Report version unavailable. Reload the AI review tab.'); return
                    self._serve_artifact('path='+quote(artifact['path'],safe=''),embedded=True)
                else:
                    self._error(404,'Workspace API not found.')
            elif parsed.path in ('/','/dashboard.html'):
                page=(ASSETS/'dashboard.html').read_text().replace('__CSRF_TOKEN__',html.escape(self.server.csrf_token,quote=True))
                # no-store would stop Chrome's back/forward cache, so Back from the workspace reloaded everything.
                self._send(200,page,'text/html; charset=utf-8',cache='private, no-cache')
            elif parsed.path in ('/assets/ai-settings.js','/assets/ai-settings.css','/assets/dashboard.css','/assets/dashboard.js','/assets/reporting.js','/assets/theme.js','/assets/queue.js','/assets/triage.js','/assets/live-review.js'):
                path=ASSETS/Path(parsed.path).name
                self._send(200,path.read_bytes(),'text/css' if path.suffix=='.css' else 'text/javascript')
            elif parsed.path in ('/api/state','/api/reporting','/status','/api/review','/api/review-events'):
                if self.headers.get('Sec-Fetch-Site') == 'cross-site' or (self.headers.get('Origin') and not self._valid_origin()):
                    self._error(403,'Dashboard state is only available from this origin.'); return
                if parsed.path in ('/api/review', '/api/review-events'):
                    run_id = (parse_qs(parsed.query).get('run_id') or [''])[0]
                    if parsed.path == '/api/review-events':
                        self._review_events(run_id)
                    else:
                        self._send(200, reviews.snapshot(run_id))
                elif parsed.path == '/api/reporting':
                    self._send(200,reporting.snapshot())
                elif parsed.path == '/api/state':
                    self._send(200,runtime.snapshot())
                else:
                    url=(parse_qs(parsed.query).get('url') or [''])[0]
                    run=dashboard.latest_run_status(url)
                    self._send(200,runtime.summarize_run(run) if run else {'status':'none','run_id':None})
            elif parsed.path == '/artifact':
                self._serve_artifact(parsed.query)
            elif parsed.path == '/favicon.ico':
                self._send(204,b'','image/x-icon')
            else:
                self._error(404,'Page not found.')
        except (OSError, ValueError, dashboard.DashboardError, tracker.TrackerError) as error:
            self._error(400,str(error))

    def do_POST(self):
        if not self._valid_host() or not self._valid_origin() or not secrets.compare_digest(
                self.headers.get('X-CSRF-Token',''),self.server.csrf_token):
            self._error(403,'Action rejected. Reload the dashboard and try again.'); return
        path=urlparse(self.path).path
        if path not in MUTATIONS:
            self._error(404,'Action not found.'); return
        try:
            length=int(self.headers.get('Content-Length','0'))
            if not 0 < length <= (650000 if path == '/workspace-save' else 100000 if path == '/workspace-chat' else 50000 if path == '/workspace-comment' else 16384) or self.headers.get('Content-Type','').split(';')[0] != 'application/json':
                self._error(400,'Expected a small JSON request.'); return
            data=json.loads(self.rfile.read(length))
            if not isinstance(data,dict):
                raise ValueError('Expected an object.')
            if path == '/workspace-save':
                self._send(200,workspace.save(str(data.get('url','')),data)); return
            if path == '/workspace-chat':
                self._send(202,workspace_chat.start(str(data.get('url','')),data)); return
            if path == '/workspace-chat-cancel':
                self._send(200,workspace_chat.cancel(str(data.get('url','')),data.get('thread_id'))); return
            if path == '/workspace-comment':
                self._send(200,workspace.post_finding(str(data.get('url','')), data)); return
            if path == '/review-cancel':
                self._send(200, reviews.cancel(str(data.get('run_id', '')))); return
            if path == '/review-message':
                self._send(202, reviews.send_message(str(data.get('run_id', '')), data.get('text', ''),
                    data.get('wrap_up') is True)); return
            if path == '/artifact-opened':
                self._send(200, runtime.mark_artifact_opened(str(data.get('run_id', '')),
                    str(data.get('name', '')), data.get('version'))); return
            if path == '/copy-prompt':
                canonical, *_ = tracker.canonical_pr_url(str(data.get('url', '')))
                kind = data.get('kind')
                if kind not in ('review', 'explainer'):
                    raise ValueError('Choose a review or explainer prompt.')
                prompt = (dashboard.full_review_prompt if kind == 'review' else dashboard.explainer_prompt)(canonical)
                self._send(200, {'prompt': prompt}); return
            if path == '/ai-config':
                if not isinstance(data.get('revision'), str):
                    raise ValueError('Reload AI settings before saving.')
                self._send(200, ai_settings.save(data.get('settings'), data['revision'])); return
            if path == '/triage-config':
                self._send(200, triage.configure(data)); return
            if path == '/triage-feedback':
                self._send(200, triage.feedback(str(data.get('url', '')), data.get('estimate_id'), data.get('rating'))); return
            if path == '/triage-reestimate':
                self._send(202, {'started': triage.start(str(data.get('url', '')), data.get('estimate_id'))}); return
            if path == '/triage-run':
                self._send(202, {'started': triage.start()}); return
            if path == '/refresh-reporting':
                self._send(202,{'started':reporting.start_refresh()}); return
            if path == '/refresh':
                queue.start_refresh(force=True, triage_after=True, manual=True)
                self._send(202,{'started':runtime.start_refresh()}); return
            if path == '/refresh-queue' and 'urls' in data:
                urls = data['urls']
                if not isinstance(urls, list) or not 0 < len(urls) <= 50 or any(not isinstance(u, str) for u in urls):
                    raise ValueError('Choose up to 50 saved PRs to check.')
                self._send(202, {'started':queue.start_fetch([tracker.canonical_pr_url(u)[0] for u in urls])}); return
            if path in ('/refresh-queue', '/recover-reviews'):
                self._send(202, {'started':queue.start_refresh(force=data.get('force') is True or path == '/recover-reviews',
                                                             recovery=path == '/recover-reviews')}); return
            if path == '/queue':
                result = queue.mutate(str(data.get('url', '')), str(data.get('action', '')), data)
                self._send(200, result)
                if data.get('action') in ('enqueue', 'restore'):
                    # Check just this PR so adding one does not hold up a full Sync.
                    queue.start_fetch([tracker.canonical_pr_url(str(data.get('url', '')))[0]])
                return
            if path in ('/regenerate-review','/regenerate-explainer'):
                result=runtime.start_launch(str(data.get('url','')),
                    'review' if path.endswith('review') else 'explainer', retry=data.get('retry') is True,
                    guidance=data.get('guidance', ''), mode=str(data.get('mode') or 'full'),
                    workspace_context=data.get('workspace_context'), deep_explanation=data.get('deep_explanation') is True)
                self._send(202,result); return
            if path in ('/snooze', '/unsnooze'):
                if path == '/snooze' and data.get('days') is None:
                    raise ValueError('Choose a snooze duration.')
                self._send(200, dashboard.set_snooze(str(data.get('url', '')),
                           data.get('days') if path == '/snooze' else None)); return
            if path == '/set-config':
                dashboard.save_agent_config(str(data.get('agent','')),str(data.get('model','')),str(data.get('effort','')))
            elif path == '/add-repo':
                dashboard.add_watched_repo(str(data.get('repo','')))
            elif path == '/remove-repo':
                dashboard.remove_watched_repo(str(data.get('repo','')))
            elif path == '/add-host-repo':
                dashboard.add_host_execution_repo(str(data.get('repo','')))
            elif path == '/remove-host-repo':
                dashboard.remove_host_execution_repo(str(data.get('repo','')))
            else:
                dashboard.set_flag(str(data.get('url','')), 'hidden',path == '/hide')
            self._send(200,{'ok':True})
        except (OSError, ValueError, dashboard.DashboardError, tracker.TrackerError) as error:
            self._error(400,str(error))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=dashboard.SERVER_PORT)
    args=parser.parse_args()
    status=tracker.tracker_root()/'dashboard-refresh.json'
    if tracker.read_json(status,required=False).get('status') == 'running':
        tracker.atomic_write(status,{'status':'failed','message':'The server restarted during refresh. Retry the GitHub refresh.'})
    server=Server((dashboard.SERVER_HOST,args.port))
    ai_cost.start_backfill()
    print(f'PR dashboard ready at http://127.0.0.1:{args.port}/',flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

"""Exercise production workspace routes using synthetic GitHub/model boundaries."""
import _bootstrap  # Make this checkout's scripts and test helpers importable.

import argparse
from contextlib import ExitStack
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
from unittest.mock import patch
import workspace_fixture_data as fixture
import workspace_github as github
import workspace_store as store
import workspace_chat as chat
import workspace_comments as comments
import code_workspace as workspace
import pr_dashboard as dashboard
import pr_review_tracker as tracker
import pr_server

SESSION='4c099c4b-400d-4914-a857-53605e88f11a'
URL='https://github.com/example/telemetry-sdk/pull/248'
CHAT_ANSWER = """Synthetic transport answer. <script>must stay text</script>

### Why the keys stay separate

- **Current code:** `namespace-record` includes the supplied namespace.
- **Default:** each application uses its own storage domain.

| Setup | Storage | Key |
| --- | --- | --- |
| Default | `UserDefaults.standard` | `otel-session-record` |
| Shared group | App group suite | `mobile-session-record` |

```swift
let key = "mobile-session-record"
let deliberatelyLongLine = "a source line that is intentionally long enough to scroll horizontally instead of stretching the chat panel or overflowing the page"
```

[Read the documentation](https://www.w3.org/TR/trace-context/).
"""



def main():
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=0);args=parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='review-connected-fixture-') as root, ExitStack() as stack:
        os.environ['PR_REVIEW_TRACKER_HOME']=root
        comparison=fixture.comparison()
        comparison.update(url=URL,base='a'*40,head='b'*40,prState='open')
        comparison['revision']=github.revision(comparison['base'],comparison['head'])
        for f in comparison['files']:
            f['fingerprint']=hashlib.sha256(json.dumps(f['rows']).encode()).hexdigest()
            f['patch']='\n'.join(r['text'] for r in f['rows'] if r['kind']!='context')
        tracker.atomic_write(store.directory(URL)/(comparison['revision']+'.json'),comparison)
        report=Path(root)/'report.html';report.write_text('<!doctype html><style>'+ (Path(__file__).resolve().parents[2]/'assets/review.css').read_text() + '</style><main><div class="topbar"><button id="theme">Theme: System</button></div>' + '<h1>Fixture AI review</h1><p>A registered report rendered inside the workspace.</p><a href="https://github.com/example/telemetry-sdk/blob/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb/src/transports/batch.ts#L40">Inspect guard</a><details class="review-finding"><summary>P2 · Fixture finding</summary><p>The guard changes the batching behavior.</p><section class="review-comment"><p>Could we keep the existing batching behavior?</p></section></details><script>document.body.dataset.script="works"</script>' + '<details><summary>Validation details</summary>' + '<p>Verification evidence and review context.</p>'*40 + '</details></main>')
        run_directory=Path(root)/'runs'/'fixture';run_directory.mkdir(parents=True)
        (run_directory/'review.md').write_text('<details class="review-finding">\n<summary>P2 · Fixture finding</summary>\n\n**P2 · Comment · Source-verified** · [existing thread](https://github.com/example/telemetry-sdk/pull/248#discussion_r42)\n\n<!-- review-comment:start -->\nCould we keep the existing batching behavior?\n<!-- review-comment:end -->\n\n</details>')
        artifact={'path':str(report),'version':'fixture-v1','head_sha':comparison['head'],'status':'completed','name':'review-html','run_id':'fixture'}
        def load_manifest(url, progress=None):
            result=copy.deepcopy(comparison)
            for f in result['files']:f['rows']=None
            return result
        def file_diff(url,rev,path):return copy.deepcopy(next(f for f in comparison['files'] if f['path']==path))
        def launch(url,thread_id):
            for delay,message in [(1,'Connecting to Codex…'),(3,'Analyzing code…'),(5,'Reading · head · src/transports/types.ts')]:
                threading.Timer(delay,chat.record_progress,args=(url,thread_id,message)).start()
            def partial():
                with store.locked(url):
                    thread=chat.read(url,thread_id)
                    if thread['status']=='running':
                        thread['draft']='Streaming answer <script>must stay text</script>'
                        chat.save(url,thread)
            threading.Timer(4,partial).start()
            def finish():
                with store.locked(url):
                    thread=chat.read(url,thread_id)
                    if thread.get('cancel'):thread.update(status='cancelled',error='Stopped.')
                    else:
                        thread['messages'].append({'role':'assistant','text':CHAT_ANSWER, 'contexts':thread['contexts'],'reads':[{'kind':'read_file','path':'src/transports/types.ts','side':'head'}, {'kind':'web_search','query':'W3C trace context'}], 'sources':[{'title':'Example source link (fixture)','url':'https://www.w3.org/TR/trace-context/'}]})
                        thread['status']='completed'
                        thread['draft']=''
                    chat.save(url,thread)
            threading.Timer(8,finish).start()
        real_start=chat.start
        stack.enter_context(patch.object(github,'manifest',side_effect=load_manifest))
        stack.enter_context(patch.object(github,'file_diff',side_effect=file_diff))
        stack.enter_context(patch.object(workspace,'review',return_value={'artifact':artifact,'run':None,'continuation':{'agent':'Claude Code','session_id':SESSION,'command':'cd /tmp/reviews && claude --resume '+SESSION+' --fork-session','prompt':'Pick up where an earlier Claude Code review left off.\nSession ID: '+SESSION}}))
        stack.enter_context(patch.object(chat,'start',side_effect=lambda url,request:real_start(url,request,launcher=launch)))
        stack.enter_context(patch.object(dashboard,'discover_claude_options',return_value=([''],[''])))
        stack.enter_context(patch.object(comments,'fetch',side_effect=lambda url:fixture.review_comments(comparison['head'])))
        stack.enter_context(patch.object(comments,'post',return_value={'posted':True,'url':'https://github.com/example/telemetry-sdk/pull/248#discussion_r43'}))
        # Fail closed: the fixture must never reach GitHub or a provider.
        stack.enter_context(patch.object(comments,'graphql',side_effect=AssertionError('Fixture network disabled')))
        stack.enter_context(patch.object(github,'api',side_effect=AssertionError('Fixture network disabled')))
        stack.enter_context(patch.object(pr_server.runtime,'mark_artifact_opened',return_value={'opened':True}))
        stack.enter_context(patch.object(pr_server.runtime,'start_launch',return_value={'run_id':'fixture','transport':'in-app'}))
        dashboard.save_dashboard({'prs':{URL:{'owner':'example','repository':'telemetry-sdk','number':248,'title':comparison['title'],'reasons':['review-requested'],'head_sha':comparison['head']}}})
        server=pr_server.Server(('127.0.0.1',args.port))
        print(f'http://127.0.0.1:{server.server_port}/workspace?url={URL}&tab=code',flush=True)
        try:server.serve_forever()
        finally:server.server_close()


if __name__=='__main__':main()

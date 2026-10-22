"""Real workspace service contracts, with GitHub and model boundaries replaced."""
import base64
import copy
import json
import os
from pathlib import Path
import tempfile
import subprocess
import sys
import time
import unittest
from unittest.mock import patch
import workspace_github as github
import code_workspace
import workspace_store as store
import workspace_chat as chat
import workspace_comments as comments
import workspace_context as private_context
import pr_review_tracker as tracker

URL='https://github.com/example/repo/pull/1'
BASE='a'*40
HEAD='b'*40
REV=BASE+'-'+HEAD


def manifest():
    return {'url':URL,'repository':'example/repo','number':1,'title':'Test PR','author':'alex',
            'base':BASE,'head':HEAD,'revision':REV,'files':[
                {'path':'src/a.ts','previous':None,'status':'modified','sha':'c'*40,'patch':'@@ -1 +1 @@\n-old\n+new',
                 'fingerprint':'first','additions':1,'deletions':1,'rows':None},
                {'path':'src/b.ts','fingerprint':'unchanged','status':'modified','patch':'@@ -1 +1 @@\n-a\n+b'}]}


class Workspace(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.env=patch.dict(os.environ,{'PR_REVIEW_TRACKER_HOME':self.temp.name});self.env.start()
        self.comparison=manifest()
        tracker.atomic_write(store.directory(URL)/(REV+'.json'),self.comparison)
    def tearDown(self):
        self.env.stop();self.temp.cleanup()

    def test_viewed_changes_only_when_comparison_changes(self):
        state=store.reconcile(URL,self.comparison)
        state=store.save(URL,self.comparison,{'version':state['version'],'revision':REV,
            'viewed':['src/a.ts','src/b.ts'],'collapsed':[],'notes':[{'text':'Private'}]})
        changed=copy.deepcopy(self.comparison);changed['revision']='next';changed['files'][0]['fingerprint']='changed'
        state=store.reconcile(URL,changed)
        self.assertEqual(state['viewed'],{'src/b.ts':'unchanged'})
        self.assertEqual(state['notes'][0]['text'],'Private')
        self.assertTrue(state['notes'][0]['id'])
        self.assertTrue(state['notes'][0]['created_at'])

    def test_selected_notes_and_conversations_are_quoted_without_tool_logs(self):
        state=store.reconcile(URL,self.comparison)
        state=store.save(URL,self.comparison,{'version':state['version'],'revision':REV,'viewed':[],'collapsed':[],
            'notes':[{'text':'Check the timeout edge','head':HEAD,'base':BASE}]})
        note_id=state['notes'][0]['id']
        thread_id='11111111-1111-1111-1111-111111111111'
        chat.save(URL,{'id':thread_id,'base':BASE,'head':HEAD,'status':'completed','messages':[
            {'role':'user','text':'What should the review verify?'},
            {'role':'assistant','text':'Verify the timer cleanup.','reads':[{'kind':'read_file','path':'secret'}],
             'sources':[{'url':'https://secret.example'}]}]})
        sources=private_context.summaries(URL,HEAD)
        self.assertEqual(sources['notes'][0]['id'],note_id)
        self.assertEqual(sources['conversations'][0]['id'],thread_id)
        prompt,meta=private_context.build(URL,{'notes':[note_id],'conversations':[thread_id]},HEAD)
        self.assertIn('Check the timeout edge',prompt)
        self.assertIn('What should the review verify?',prompt)
        self.assertIn('Verify the timer cleanup.',prompt)
        self.assertNotIn('secret.example',prompt)
        self.assertNotIn('read_file',prompt)
        self.assertEqual(meta['notes'],[note_id])
        with self.assertRaisesRegex(ValueError,'no longer available'):
            private_context.build(URL,{'notes':['missing-note']},HEAD)

    def test_context_sources_are_isolated_per_pull_request(self):
        other_url='https://github.com/example/repo/pull/2'
        other_state=store.reconcile(other_url,self.comparison)
        other_state=store.save(other_url,self.comparison,{'version':other_state['version'],'revision':REV,'viewed':[],'collapsed':[],
            'notes':[{'id':'other-note-1','text':'Other PR note'}]})
        other_thread='22222222-2222-2222-2222-222222222222'
        chat.save(other_url,{'id':other_thread,'base':BASE,'head':HEAD,'status':'completed','messages':[
            {'role':'user','text':'Other PR question'},
            {'role':'assistant','text':'Other PR answer'}]})
        current=private_context.summaries(URL,HEAD)
        self.assertNotIn('other-note-1',{item['id'] for item in current['notes']})
        self.assertNotIn(other_thread,{item['id'] for item in current['conversations']})
        with self.assertRaisesRegex(ValueError,'no longer available'):
            private_context.build(URL,{'notes':['other-note-1']},HEAD)
        with self.assertRaisesRegex(ValueError,'no longer available'):
            private_context.build(URL,{'conversations':[other_thread]},HEAD)
        self.assertEqual(other_state['notes'][0]['id'],'other-note-1')

    def test_historical_note_save_does_not_change_latest_progress(self):
        state=store.reconcile(URL,self.comparison)
        request={'version':state['version'],'revision':REV,'viewed':['src/a.ts'],'collapsed':[],'notes':[]}
        state=store.save(URL,self.comparison,request)
        historical={**request,'version':state['version'],'revision':'older','viewed':[],'notes':[{'text':'An old revision note'}]}
        state=store.save(URL,self.comparison,historical)
        self.assertEqual(state['viewed'],{'src/a.ts':'first'})
        self.assertEqual(state['notes'][0]['text'],'An old revision note')

    def test_stale_tabs_cannot_overwrite_progress(self):
        state=store.reconcile(URL,self.comparison)
        request={'version':state['version'],'revision':REV,'viewed':[],'collapsed':[],'notes':[]}
        store.save(URL,self.comparison,request)
        with self.assertRaisesRegex(ValueError,'another tab'):store.save(URL,self.comparison,request)

    def test_diff_roundtrip_and_line_numbers(self):
        for before,after in [('a\nb\nc\n','a\nx\ny\nc\n'),('','new'),('old',''),('same','same')]:
            rows=github.rows(before,after)
            self.assertEqual([r['text'] for r in rows if r['old'] is not None],before.splitlines())
            self.assertEqual([r['text'] for r in rows if r['new'] is not None],after.splitlines())
            self.assertEqual([r['old'] for r in rows if r['old'] is not None],list(range(1,len(before.splitlines())+1)))

    def test_file_reads_use_pinned_revision_and_previous_rename_path(self):
        self.comparison['files'][0].update(status='renamed',previous='old name.ts')
        tracker.atomic_write(store.directory(URL)/(REV+'.json'),self.comparison)
        with patch.object(github,'api',return_value={'type':'file','size':4,'encoding':'base64','content':base64.b64encode(b'test').decode()}) as api:
            result=github.file_diff(URL,REV,'src/a.ts')
            endpoints=[c.args[0] for c in api.call_args_list]
            self.assertTrue(any('old%20name.ts?ref='+BASE in e for e in endpoints))
            self.assertTrue(any('src/a.ts?ref='+HEAD in e for e in endpoints))
            self.assertTrue(result['headNoNewline'])
        with patch.object(github,'api',side_effect=AssertionError('must use cache')):
            self.assertEqual(github.file_diff(URL,REV,'src/a.ts'),result)

    def test_unsafe_paths_binary_and_large_files_fail_explicitly(self):
        for path in ['../secret','/tmp/secret','a/../secret']:
            with self.assertRaises(ValueError):github.read_file(self.comparison,path)
        for data in [{'type':'symlink'},{'type':'file','size':500001},
                     {'type':'file','size':2,'encoding':'base64','content':'AAA='}]:
            with patch.object(github,'api',return_value=data),self.assertRaises(ValueError):
                github.read_file(self.comparison,'src/a.ts')
        with self.assertRaises(ValueError):github.cached(URL,'../../outside')

    def test_context_uses_server_source_not_client_snippet(self):
        context={'path':'src/a.ts','side':'head','base':BASE,'head':HEAD,'ids':[1],'snippet':'forged'}
        with patch.object(github,'file_diff',return_value={**self.comparison['files'][0],'rows':github.rows('old','new')}):
            result=chat.normalize_contexts(URL,self.comparison,[context])
        self.assertIn('new',result[0]['snippet']);self.assertNotIn('forged',result[0]['snippet'])
        with self.assertRaises(ValueError):chat.normalize_contexts(URL,self.comparison,[{**context,'head':'x'}])

    def test_chat_continuity_is_durable_and_duplicate_turn_blocked(self):
        with patch.object(chat,'normalize_contexts',return_value=[]):
            first=chat.start(URL,{'revision':REV,'question':'Explain it','contexts':[]},launcher=lambda *a:None)
            with self.assertRaisesRegex(ValueError,'current answer'):
                chat.start(URL,{'revision':REV,'thread_id':first['id'],'question':'Again'},launcher=lambda *a:None)
            saved=chat.read(URL,first['id']);saved['status']='completed';saved['messages'].append({'role':'assistant','text':'Answer','contexts':[]});chat.save(URL,saved)
            second=chat.start(URL,{'revision':REV,'thread_id':first['id'],'question':'Why?'},launcher=lambda *a:None)
            self.assertEqual(len(second['messages']),3)
            self.assertEqual(second['id'],first['id'])
            stopped=chat.cancel(URL,first['id']);self.assertEqual(stopped['status'],'stopping')

    def test_context_bootstrap_and_resume_do_not_replay_history(self):
        thread={'messages':[{'role':'user','text':'Earlier'}, {'role':'assistant','text':'Prior answer'},
                            {'role':'user','text':'Why?'}], 'contexts':[]}
        first=json.loads(chat.turn_context(self.comparison,thread))
        self.assertEqual(first['comparison']['head'],HEAD)
        self.assertEqual(len(first['previous_messages']),2)
        self.assertIn('diff',first)
        resumed=json.loads(chat.turn_context(self.comparison,{**thread,'codex_context_seeded':True}))
        self.assertEqual(resumed['question'],'Why?')
        self.assertNotIn('previous_messages',resumed)
        self.assertNotIn('diff',resumed)

    def test_bootstrap_context_is_bounded(self):
        with self.assertRaisesRegex(ValueError,'180 KB'):
            chat.turn_context(self.comparison,{'contexts':[], 'messages':[{'text':'x'*200_000}]})

    def test_cancel_stops_only_the_dedicated_chat_worker(self):
        thread=chat.start(URL,{'revision':REV,'question':'Wait','contexts':[]},launcher=lambda *args:None)
        code = r"""
import sys,time
from pathlib import Path
from types import SimpleNamespace as NS
import workspace_chat as chat
class FakeProvider:
 def run(self,request,callbacks):
  (chat.store.directory(sys.argv[1])/'provider-ready').touch()
  time.sleep(60)
 def close(self):pass
chat.ai_runtime.create=lambda _:FakeProvider()
sys.modules['workspace_checkout']=NS(prepare=lambda _:chat.store.directory(sys.argv[1]))
chat.worker(sys.argv[1],sys.argv[2])
"""
        process=subprocess.Popen([sys.executable,'-c',code,URL,thread['id']],
                                 cwd=Path(__file__).resolve().parents[2] / 'scripts',start_new_session=True)
        try:
            deadline=time.monotonic()+5
            while not (store.directory(URL)/'provider-ready').exists() and time.monotonic()<deadline:time.sleep(.02)
            self.assertTrue((store.directory(URL)/'provider-ready').exists())
            chat.cancel(URL,thread['id'])
            self.assertEqual(process.wait(timeout=5),-15)
            self.assertEqual(chat.read(URL,thread['id'])['status'],'cancelled')
        finally:
            if process.poll() is None:process.kill();process.wait()

    def test_provider_and_model_pinned_across_settings_changes(self):
        import ai_settings
        from types import SimpleNamespace as NS
        first=chat.start(URL,{'revision':REV,'question':'Explain'},launcher=lambda *a:None)
        settings=ai_settings.load();settings['chat']['provider']='claude';ai_settings.save(settings)
        seen=[]
        class Provider:
            def run(self,request,callbacks):
                seen.append(request);callbacks.session('native-session')
                return {'completed':True,'answer':'Answer','sources':[]}
            def close(self):pass
        with patch.object(chat.ai_runtime,'create',return_value=Provider()) as create, patch.dict(sys.modules,{'workspace_checkout':NS(prepare=lambda _:store.directory(URL))}):
            chat.worker(URL,first['id'])
            create.assert_called_once_with('codex')
        resumed=chat.start(URL,{'revision':REV,'thread_id':first['id'],'question':'Again'},launcher=lambda *a:None)
        self.assertEqual(resumed['ai_config'],first['ai_config'])
        self.assertEqual(resumed['provider_session_id'],'native-session')
        new=chat.start(URL,{'revision':REV,'question':'New'},launcher=lambda *a:None)
        self.assertEqual(new['ai_config']['provider'],'claude')

    def test_legacy_sessions_remain_codex(self):
        import ai_settings
        thread={'id':'a'*8+'-'+ 'b'*4+'-'+ 'c'*4+'-'+ 'd'*4+'-'+ 'e'*12,
                'codex_thread_id':'old-session','codex_context_seeded':True}
        chat.save(URL,thread)
        settings=ai_settings.load();settings['chat']['provider']='claude';ai_settings.save(settings)
        loaded=chat.read(URL,thread['id'])
        self.assertEqual(loaded['ai_config']['provider'],'codex')
        self.assertEqual(loaded['provider_session_id'],'old-session')
        self.assertTrue(loaded['context_seeded'])

    def test_manifest_reports_step_weighted_progress(self):
        pr={'head':{'sha':HEAD},'base':{'sha':BASE},'changed_files':1,'title':'PR','user':{'login':'x'},'state':'open'}
        tree={'tree':[{'path':'x','mode':'100644','sha':'c'*40}]}
        steps=[]
        with patch.object(github,'api',side_effect=[pr,{'merge_base_commit':{'sha':'d'*40}},[{'filename':'x','status':'added'}],pr,tree,tree]):
            github.manifest(URL,lambda step,done,total=None,**details:steps.append((step,done,total,details)))
        self.assertEqual([(s[0],s[1],s[2]) for s in steps],[
            ('Reading the pull request',0,None),('Finding the merge base',1,9),('Listing changed files',2,9),
            ('Checking for new commits',3,9),('Reading the base file tree',4,9),('Reading the head file tree',6,9),
            ('Restoring your review state',8,9)])
        self.assertEqual(steps[1][3],{'title':'PR','repository':'example/repo','number':1})
        steps.clear()
        with patch.object(github,'api',side_effect=[pr,{'merge_base_commit':{'sha':'d'*40}}]):
            github.manifest(URL,lambda step,done,total=None,**_:steps.append((step,done,total)))
        self.assertEqual(steps[-1],('Restoring your review state',2,3))

    def test_manifest_detects_commit_race(self):
        pr={'head':{'sha':HEAD},'base':{'sha':BASE},'changed_files':1,'title':'PR','user':{'login':'x'},'state':'open'}
        with patch.object(github,'api',side_effect=[pr,{'merge_base_commit':{'sha':'d'*40}},[{'filename':'x'}],{**pr,'head':{'sha':'e'*40}}]):
            with self.assertRaisesRegex(ValueError,'changed while loading'):github.manifest(URL)

    def github_comments(self):
        def page(name,nodes,more=False):
            return {'viewer':{'login':'me'},'repository':{'pullRequest':{'headRefOid':HEAD,name:{
                'pageInfo':{'hasNextPage':more,'endCursor':'next' if more else None},'nodes':nodes}}}}
        note=lambda id,body,login='sam',kind='User',**extra:{'id':id,'author':{'login':login,'__typename':kind},
            'authorAssociation':'MEMBER','body':body,'createdAt':extra.pop('at','2026-01-01T00:00:00Z'),'url':'https://github.com/x',**extra}
        threads=[{'id':'T1','isResolved':False,'isOutdated':False,'path':'src/a.ts','line':1,'startLine':None,
                  'originalLine':1,'originalStartLine':None,'diffSide':'RIGHT','subjectType':'LINE',
                  'comments':{'totalCount':3,'nodes':[note('c1','Use a guard <script>',diffHunk='@@ hunk')]}}]
        left={**threads[0],'id':'T2','diffSide':'LEFT','isResolved':True,
              'comments':{'totalCount':1,'nodes':[note('c2','ok','ci[bot]','Bot')]}}
        return [page('reviewThreads',threads,True),page('reviewThreads',[left]),
                page('comments',[note('i1','Later',at='2026-01-03T00:00:00Z')]),
                page('reviews',[note('r1','',state='APPROVED'),note('r2','Needs tests',state='CHANGES_REQUESTED',at='2026-01-02T00:00:00Z')])]

    def test_posting_a_finding_uses_the_pinned_head_and_invalidates_comments(self):
        response = subprocess.CompletedProcess([], 0, stdout=json.dumps({'id': 123, 'html_url': 'https://github.com/example/repo/pull/1#discussion_r123'}).encode(), stderr=b'')
        with patch.object(comments.subprocess, 'run', return_value=response) as run:
            result = comments.post(URL, {'revision': REV, 'body': 'Please keep this guard.',
                                         'target': {'mode': 'inline', 'commit_id': HEAD,
                                                    'path': 'src/a.ts', 'line': 4, 'side': 'RIGHT'}})
        self.assertTrue(result['posted'])
        command = run.call_args.args[0]
        self.assertIn('repos/example/repo/pulls/1/comments', command)
        self.assertIn('commit_id=' + HEAD, command)
        self.assertIn('line=4', command)
        self.assertIn('side=RIGHT', command)
        with self.assertRaisesRegex(ValueError, 'pinned pull request head'):
            comments.post(URL, {'revision': REV, 'body': 'x',
                                'target': {'mode': 'inline', 'commit_id': BASE,
                                           'path': 'src/a.ts', 'line': 4, 'side': 'RIGHT'}})

    def test_posting_a_finding_can_reply_to_a_review_comment(self):
        response = subprocess.CompletedProcess([], 0, stdout=b'{"html_url":"https://github.com/example/repo/pull/1#discussion_r9"}', stderr=b'')
        with patch.object(comments.subprocess, 'run', return_value=response) as run:
            comments.post(URL, {'revision': REV, 'body': 'The latest commit still has this case.',
                                'target': {'mode': 'reply', 'in_reply_to': 9}})
        command = run.call_args.args[0]
        self.assertIn('repos/example/repo/pulls/1/comments', command)
        self.assertIn('body=The latest commit still has this case.', command)
        self.assertIn('in_reply_to=9', command)

    def test_review_finding_attachment_uses_saved_report_not_browser_title(self):
        run_id = 'finding-run'
        directory = tracker.tracker_root() / 'runs' / run_id
        directory.mkdir(parents=True, exist_ok=True)
        (directory / 'review.md').write_text('<details class="review-finding">\n<summary>P2 · Keep the guard</summary>\n\n<!-- review-comment:start -->\nDraft\n<!-- review-comment:end -->\n</details>')
        with patch.object(code_workspace, 'review', return_value={'artifact': {'run_id': run_id, 'head_sha': HEAD}}):
            [context] = chat.normalize_contexts(URL, self.comparison, [{
                'kind': 'finding', 'finding': 1, 'report_head': HEAD,
                'base': BASE, 'head': HEAD, 'label': 'forged title'}])
        self.assertEqual(context['label'], 'Finding 1 · P2 · Keep the guard')
        self.assertNotIn('forged title', context['snippet'])
        self.assertIn('review.md', context['snippet'])

    def test_finding_preview_rebuilds_an_existing_reply_target_from_the_saved_report(self):
        run_id = 'finding-reply-target-run'
        directory = tracker.tracker_root() / 'runs' / run_id
        directory.mkdir(parents=True, exist_ok=True)
        (directory / 'review.md').write_text(
            '<details class="review-finding">\n<summary>P2 · Keep the guard</summary>\n\n'
            '**P2 · Comment · Source-verified** · '
            '[existing thread](https://github.com/example/repo/pull/1#discussion_r9)\n\n'
            '<!-- review-comment:start -->\nDraft\n<!-- review-comment:end -->\n'
            '</details>')
        with patch.object(code_workspace, 'review', return_value={
                'artifact': {'run_id': run_id, 'head_sha': HEAD, 'version': 'v1'}}):
            result = code_workspace.finding(URL, REV, 'v1', 'finding-1')
        self.assertTrue(result['can_post'])
        self.assertEqual(result['target']['mode'], 'reply')
        self.assertEqual(result['target']['in_reply_to'], 9)

    def test_finding_preview_rebuilds_an_inline_target_from_the_saved_report(self):
        run_id = 'finding-target-run'
        directory = tracker.tracker_root() / 'runs' / run_id
        directory.mkdir(parents=True, exist_ok=True)
        (directory / 'review.md').write_text(
            '<details class="review-finding">\n<summary>P2 · Keep the guard</summary>\n\n'
            '**P2 · Comment · Source-verified** · '
            '[src/a.ts](https://github.com/example/repo/blob/' + HEAD + '/src/a.ts#L1-L2)\n\n'
            '<!-- review-comment:start -->\nDraft\n<!-- review-comment:end -->\n'
            '</details>')
        with patch.object(code_workspace, 'review', return_value={
                'artifact': {'run_id': run_id, 'head_sha': HEAD, 'version': 'v1'}}):
            result = code_workspace.finding(URL, REV, 'v1', 'finding-1')
        self.assertTrue(result['can_post'])
        self.assertEqual(result['target']['mode'], 'inline')
        self.assertEqual(result['target']['line'], 2)
        self.assertEqual(result['target']['start_line'], 1)

    def test_comments_are_read_with_paginated_queries_only(self):
        seen=[]
        pages=iter(self.github_comments())
        def fake(query,variables):
            seen.append((query,dict(variables)));return next(pages)
        with patch.object(comments,'graphql',side_effect=fake):
            result=comments.load(URL)
        self.assertTrue(all(q.startswith('query(') and 'mutation' not in q for q,_ in seen))
        self.assertEqual([v['cursor'] for _,v in seen[:2]],[None,'next'])
        first,second=result['threads']
        self.assertEqual((first['side'],second['side'],second['resolved']),('head','base',True))
        self.assertEqual((first['hidden_comments'],first['diff_hunk']),(2,'@@ hunk'))
        self.assertTrue(second['comments'][0]['bot'])
        self.assertEqual([c['id'] for c in result['conversation']],['r2','i1'])
        self.assertEqual(result['viewer'],'me')
        with patch.object(comments,'graphql',side_effect=AssertionError('must use recent cache')):
            self.assertEqual(comments.load(URL)['threads'],result['threads'])

    def test_comment_context_is_rebuilt_from_cached_github_data(self):
        pages=iter(self.github_comments())
        with patch.object(comments,'graphql',side_effect=lambda *a:next(pages)):comments.load(URL)
        forged={'kind':'comment','comment':'T1','base':BASE,'head':HEAD,'snippet':'forged','ids':[0]}
        file={**self.comparison['files'][0],'rows':github.rows('old','new')}
        with patch.object(github,'file_diff',return_value=file):
            [context]=chat.normalize_contexts(URL,self.comparison,[forged])
        self.assertEqual(context['ids'],[1])
        self.assertIn('Use a guard <script>',context['snippet']);self.assertNotIn('forged',context['snippet'])
        self.assertIn('Viewer: @me. PR author: @alex.',context['snippet'])
        self.assertEqual(context['label'],'@sam · Head L1')
        [review]=chat.normalize_contexts(URL,self.comparison,[{**forged,'comment':'r2'}])
        self.assertEqual((review['path'],review['ids']),('',[]))
        cache=comments.cached(URL);cache['head']='f'*40;tracker.atomic_write(comments.path(URL),cache)
        with patch.object(github,'file_diff',side_effect=AssertionError('newer comments are not placed')):
            [moved]=chat.normalize_contexts(URL,self.comparison,[forged])
        self.assertEqual(moved['ids'],[]);self.assertIn('@@ hunk',moved['snippet'])
        with self.assertRaisesRegex(ValueError,'no longer available'):
            chat.normalize_contexts(URL,self.comparison,[{**forged,'comment':'missing'}])
        with self.assertRaisesRegex(ValueError,'another revision'):
            chat.normalize_contexts(URL,self.comparison,[{**forged,'head':'x'}])


if __name__=='__main__':unittest.main()

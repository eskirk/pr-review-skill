"""Behavioral regression tests: refresh, launch lifecycle, and HTTP boundaries."""
import copy
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace as NS
import tempfile
import threading
import subprocess
import unittest
from unittest.mock import patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import pr_dashboard as d
import pr_review_tracker as t
import dashboard_runtime as r
import pr_server as s

URL='https://github.com/example/repo/pull/1'
ENTRY={'owner':'example','repository':'repo','number':1,'title':'Example PR',
       'reasons':['review-requested'],'hidden':False,'starred':True,'first_seen_at':'2026-01-01T00:00:00+00:00'}
ITEM={'url':URL,'title':'Example PR','isDraft':False,'author':{'login':'someone'}}

class Isolated(unittest.TestCase):
 def setUp(self):
  self.author_fetch=patch.object(d,'fetch_author_profile',return_value={});self.author_fetch.start();self.addCleanup(self.author_fetch.stop)
  self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name).resolve()
  self.env=patch.dict(os.environ,{'PR_REVIEW_TRACKER_HOME':str(self.root),'PR_REVIEW_TRACKER_GH':'/usr/bin/false'});self.env.start()
  self.options=patch.object(d,'discover_claude_options',return_value=(['','claude-example'],['','high']));self.options.start()
  d.save_dashboard({'prs':{URL:copy.deepcopy(ENTRY)}})
 def tearDown(self):
  self.options.stop();self.env.stop();self.tmp.cleanup()
 def create_run(self,kind='review'):
  return t.command_start(NS(pr_url=URL,tool='codex',title='Example',working_directory=str(self.root),session_reference='',base_sha='',head_sha='a'*40),emit=False)
 def task(self,run,task,status):
  t.command_set_task(NS(run_id=run,task=task,status=status,message=''))
 def complete(self,run):
  for task in t.DEFAULT_TASKS:self.task(run,task,'completed')
 def artifact(self,run,name='review-markdown',filename='notes.md'):
  path=self.root/filename;path.write_text('# Review\n\nUseful notes.')
  t.command_add_artifact(NS(run_id=run,name=name,kind='markdown',path=str(path),managed=True))
  return path
 def refresh(self,search,details=None):
  with patch.object(d,'run_gh_search',side_effect=search),patch.object(d,'run_gh_pr_list',return_value=[]),patch.object(d,'current_login',return_value='me'),patch.object(d,'fetch_pr_details',return_value=details or {'reviews':[],'comments':[]}) as fetch,patch.object(d,'rerender_from_dashboard'),patch('sys.stdout',new=io.StringIO()):
   d.command_refresh(NS())
  return fetch

class Refresh(Isolated):
 def test_failed_source_keeps_starred_open_entry_and_warning(self):
  self.refresh(lambda reason: (_ for _ in ()).throw(d.DashboardError('Search failed')) if reason=='review-requested' else [])
  data=d.load_dashboard();self.assertTrue(data['prs'][URL]['starred']);self.assertTrue(data['refresh_warnings']);self.assertFalse(data.get('last_github_refresh_at'))
 def test_complete_absence_removes_membership(self):
  self.refresh(lambda _:[]);self.assertNotIn(URL,d.load_dashboard()['prs'])
 def test_truncated_source_preserves_unseen_entries(self):
  self.refresh(lambda reason:[{**ITEM,'url':f'https://github.com/example/repo/pull/{i+2}'} for i in range(100)] if reason=='review-requested' else [])
  self.assertIn(URL,d.load_dashboard()['prs']);self.assertIn('first 100',d.load_dashboard()['refresh_warnings'][0])
 def test_partial_failure_preserves_other_reason(self):
  data=d.load_dashboard();data['prs'][URL]['reasons']=['assignee','review-requested'];d.save_dashboard(data)
  self.refresh(lambda reason: (_ for _ in ()).throw(d.DashboardError('Unavailable')) if reason=='assignee' else ([ITEM] if reason=='review-requested' else []))
  self.assertEqual(d.load_dashboard()['prs'][URL]['reasons'],['assignee','review-requested'])
 def test_opening_date_is_distinct_from_activity_and_first_seen(self):
  opened='2025-12-01T00:00:00Z'
  updated='2026-01-03T00:00:00Z'
  self.refresh(lambda reason:[{**ITEM,'createdAt':opened}] if reason=='review-requested' else [],
               {'createdAt':opened,'updatedAt':updated})
  pr=r.snapshot()['prs'][0]
  self.assertEqual(pr['pr_created_at'],opened);self.assertEqual(pr['pr_updated_at'],updated)
  self.assertNotEqual(pr['pr_created_at'],pr['first_seen_at'])
  self.refresh(lambda reason:[ITEM] if reason=='review-requested' else [])
  self.assertEqual(r.snapshot()['prs'][0]['pr_created_at'],opened)

 def test_unchanged_pr_reuses_recent_details_for_an_hour(self):
  updated,later='2026-01-03T00:00:00Z','2026-01-03T06:00:00Z'
  def refresh(at,stamp=updated):
   item={**ITEM,'updatedAt':stamp}
   with patch.object(t,'utc_now',return_value=at):
    return self.refresh(lambda reason:[item] if reason=='review-requested' else [],
                        {'reviews':[],'comments':[],'updatedAt':stamp,'headRefOid':'b'*40,'additions':4,'deletions':1,'changedFiles':2}).call_count
  self.assertEqual(refresh('2026-01-04T00:00:00+00:00'),1)
  self.assertEqual(refresh('2026-01-04T00:30:00+00:00'),0)
  self.assertEqual(d.load_dashboard()['prs'][URL]['details_checked_at'],'2026-01-04T00:00:00+00:00')
  self.assertEqual({k:d.load_dashboard()['prs'][URL][k] for k in ('additions','deletions','changed_files')},{'additions':4,'deletions':1,'changed_files':2})
  self.assertEqual(refresh('2026-01-04T01:00:00+00:00'),1)
  self.assertEqual(refresh('2026-01-04T01:10:00+00:00',later),1)
  self.assertEqual(d.load_dashboard()['prs'][URL]['pr_updated_at'],later)

 def test_search_supplies_opening_date_when_details_omit_it(self):
  opened='2025-12-01T00:00:00Z'
  self.refresh(lambda reason:[{**ITEM,'createdAt':opened}] if reason=='review-requested' else [])
  self.assertEqual(r.snapshot()['prs'][0]['pr_created_at'],opened)

 def test_comment_does_not_mark_reviewed_and_tracks_actual_state(self):
  self.refresh(lambda reason:[ITEM] if reason=='review-requested' else [],{'comments':[{'author':{'login':'me'},'createdAt':'2026-01-02T00:00:00Z'}],'reviews':[],'headRefOid':'b'*40})
  row=r.snapshot()['prs'][0];self.assertEqual(row['participation'],'Commented');self.assertFalse(row['my_review_at'])
  self.refresh(lambda reason:[ITEM] if reason=='review-requested' else [],{'comments':[],'reviews':[{'author':{'login':'me'},'submittedAt':'2026-01-03T00:00:00Z','state':'CHANGES_REQUESTED'}]})
  self.assertEqual(r.snapshot()['prs'][0]['participation'],'Changes requested')
 def test_hide_change_during_network_is_preserved(self):
  def search(reason):
   if reason=='review-requested':
    with d.state_lock():
     data=d.load_dashboard();data['prs'][URL]['hidden']=True;d.save_dashboard(data)
    return [ITEM]
   return []
  self.refresh(search);self.assertTrue(d.load_dashboard()['prs'][URL]['hidden'])
 def test_local_mutation_does_not_change_github_freshness_or_warnings(self):
  data=d.load_dashboard();data.update(last_github_refresh_at='2026-01-01T00:00:00Z',refresh_warnings=['Keep this warning']);d.save_dashboard(data)
  with patch.object(d,'render_html'):d.set_flag(URL,'hidden',True)
  after=d.load_dashboard();self.assertEqual(after['last_github_refresh_at'],'2026-01-01T00:00:00Z');self.assertEqual(after['refresh_warnings'],['Keep this warning'])

class ArtifactsAndConfig(Isolated):
 def test_new_run_does_not_hide_completed_notes(self):
  old=self.create_run();path=self.artifact(old);self.complete(old);new=self.create_run()
  row=r.snapshot()['prs'][0];self.assertEqual(row['run']['run_id'],new);self.assertEqual(row['artifacts']['review-markdown']['path'],str(path))
 def test_explainer_only_keeps_old_notes_and_labels_mixed(self):
  old=self.create_run();self.artifact(old);self.complete(old);new=self.create_run();self.artifact(new,'explanation-html','explain.html');self.complete(new)
  row=r.snapshot()['prs'][0];self.assertEqual(len(row['artifacts']),2);self.assertTrue(row['mixed_artifacts'])
 def test_missing_file_falls_back_to_previous_run(self):
  old=self.create_run();first=self.artifact(old);self.complete(old);new=self.create_run();second=self.artifact(new,filename='new.md');self.complete(new);second.unlink()
  self.assertEqual(r.snapshot()['prs'][0]['artifacts']['review-markdown']['path'],str(first))
 def test_stale_sha_is_explicit(self):
  run=self.create_run();self.artifact(run);self.complete(run)
  data=d.load_dashboard();data['prs'][URL]['head_sha']='b'*40;d.save_dashboard(data)
  self.assertEqual(r.snapshot()['prs'][0]['artifact_freshness'],'older')
 def test_agent_profiles_survive_switch_and_migrate(self):
  t.atomic_write(d.config_path(),{'agent':'claude','model':'claude-example','effort':'high','watched_repos':['example/repo']})
  d.save_agent_config('codex','gpt-example','low');cfg=d.load_config();self.assertEqual(cfg['agent_profiles']['claude']['model'],'claude-example')
  d.save_agent_config('claude',**cfg['agent_profiles']['claude']);self.assertEqual(d.load_config()['agent_profiles']['codex']['model'],'gpt-example');self.assertEqual(d.load_config()['watched_repos'],['example/repo'])
 def test_host_execution_repos_are_normalized_and_kept(self):
  t.atomic_write(d.config_path(),{'watched_repos':['example/repo']})
  self.assertEqual(d.add_host_execution_repo('https://github.com/Grafana/*'),'Grafana/*')
  d.add_host_execution_repo('grafana/*');d.add_host_execution_repo('open-telemetry/opentelemetry-swift.git')
  self.assertEqual(d.load_config()['host_execution_repos'],['Grafana/*','open-telemetry/opentelemetry-swift'])
  for bad in ('*','grafana','*/repo','grafana/**'):
   with self.assertRaises(d.DashboardError):d.add_host_execution_repo(bad)
  d.save_agent_config('codex','gpt-example','low');d.remove_host_execution_repo('grafana/*')
  self.assertEqual(d.load_config()['host_execution_repos'],['open-telemetry/opentelemetry-swift']);self.assertEqual(d.load_config()['watched_repos'],['example/repo'])
 def test_wrong_agent_model_rejected(self):
  with self.assertRaises(d.DashboardError):d.save_agent_config('codex','claude-example','')

class Launches(Isolated):
 def test_duplicate_launch_and_exact_prompt_id(self):
  with patch.object(r.reviews,'start') as launch:
   first=r.start_launch(URL,'review');second=r.start_launch(URL,'explainer')
  self.assertFalse(first['existing']);self.assertTrue(second['existing']);self.assertEqual(first['run_id'],second['run_id']);self.assertEqual(launch.call_count,1)
  self.assertIn(first['run_id'],launch.call_args.args[1]);self.assertEqual(launch.call_args.args[0],first['run_id'])
 def test_progress_survives_snapshot_and_completion_updates_artifacts(self):
  with patch.object(r.reviews,'start'):run=r.start_launch(URL,'review')['run_id']
  self.assertEqual(r.snapshot()['prs'][0]['run']['status'],'starting')
  self.task(run,'checkout','running');self.assertEqual(r.snapshot()['prs'][0]['run']['status'],'running')
  self.artifact(run);self.complete(run);row=r.snapshot()['prs'][0];self.assertEqual(row['run']['status'],'completed');self.assertIn('review-markdown',row['artifacts'])
 def test_worker_launch_failure_is_persisted(self):
  with patch.object(r.reviews,'start',side_effect=d.DashboardError('Cannot start worker')):
   with self.assertRaises(d.DashboardError):r.start_launch(URL,'review')
  self.assertEqual(r.snapshot()['prs'][0]['run']['status'],'failed')
 def test_explicit_retry_releases_tracking_without_launching_twice(self):
  with patch.object(r.reviews,'start'):
   old=r.start_launch(URL,'review')['run_id'];new=r.start_launch(URL,'review',retry=True)['run_id']
  self.assertNotEqual(old,new);self.assertEqual(t.load_run(t.run_dir(old),6)['status'],'cancelled')
 def test_retired_explainer_launch_runs_complete_review(self):
  with patch.object(r.reviews,'start') as launch:run=r.start_launch(URL,'explainer')['run_id']
  self.task(run,'checkout','completed');self.task(run,'explanation','completed')
  self.assertNotEqual(r.snapshot()['prs'][0]['run']['status'],'completed')
  self.assertIn('review-html',launch.call_args.args[1])
  self.assertEqual(r.snapshot()['prs'][0]['run']['kind'],'review')

class HTTP(Isolated):
 def setUp(self):
  super().setUp();self.server=s.Server(('127.0.0.1',0));self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start();self.base=f'http://127.0.0.1:{self.server.server_port}'
 def tearDown(self):
  self.server.shutdown();self.server.server_close();self.thread.join();super().tearDown()
 def request(self,path,method='GET',data=None,headers=None):
  request=Request(self.base+path,method=method,data=json.dumps(data or {}).encode() if method=='POST' else None,headers=headers or {})
  try:response=urlopen(request,timeout=5)
  except HTTPError as error:response=error
  with response:return response.status,response.headers,response.read()
 def auth(self):return {'Origin':self.base,'X-CSRF-Token':self.server.csrf_token,'Content-Type':'application/json'}
 def test_copy_prompts_preserve_state_and_do_not_launch(self):
  before={p.relative_to(self.root):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
  with patch.object(r.reviews,'start') as launch, patch.object(t,'command_start') as start:
   for kind,builder in [('review',d.full_review_prompt),('explainer',d.explainer_prompt)]:
    code,_,body=self.request('/copy-prompt','POST',{'url':URL,'kind':kind},self.auth())
    self.assertEqual(code,200);self.assertEqual(json.loads(body)['prompt'],builder(URL))
   self.assertEqual(self.request('/copy-prompt','POST',{'url':URL,'kind':'review'})[0],403)
   self.assertEqual(self.request('/copy-prompt','POST',{'url':URL,'kind':'unknown'},self.auth())[0],400)
   self.assertEqual(self.request('/copy-prompt','POST',{'url':'not a PR','kind':'review'},self.auth())[0],400)
   launch.assert_not_called();start.assert_not_called()
  after={p.relative_to(self.root):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
  self.assertEqual(before,after)
 def test_reporting_uses_same_origin_and_authenticated_refresh(self):
  self.assertEqual(self.request('/api/reporting',headers={'Origin':'https://elsewhere.example'})[0],403)
  self.assertEqual(self.request('/api/reporting',headers={'Sec-Fetch-Site':'cross-site'})[0],403)
  self.assertEqual(self.request('/api/reporting')[0],200)
  self.assertEqual(self.request('/assets/reporting.js')[0],200)
  with patch.object(s.reporting,'start_refresh',return_value=True) as refresh:
   self.assertEqual(self.request('/refresh-reporting','POST',{})[0],403)
   refresh.assert_not_called()
   self.assertEqual(self.request('/refresh-reporting','POST',{},self.auth())[0],202)
   refresh.assert_called_once()
 def test_all_mutating_gets_rejected(self):
  for path in s.MUTATIONS:self.assertEqual(self.request(path)[0],405,path)
 def test_post_requires_token_and_same_origin(self):
  self.assertEqual(self.request('/hide','POST',{'url':URL})[0],403)
  headers=self.auth();headers['Origin']='https://unrelated.example';self.assertEqual(self.request('/hide','POST',{'url':URL},headers)[0],403)
  headers=self.auth();headers['X-CSRF-Token']='invalid';self.assertEqual(self.request('/hide','POST',{'url':URL},headers)[0],403)
  self.assertFalse(d.load_dashboard()['prs'][URL]['hidden'])
 def test_concurrent_preferences_do_not_overwrite_each_other(self):
  other=URL+'2'
  data=d.load_dashboard();data['prs'][other]={**ENTRY,'number':12};d.save_dashboard(data)
  from concurrent.futures import ThreadPoolExecutor
  with ThreadPoolExecutor(max_workers=2) as pool:
   results=list(pool.map(lambda url:self.request('/hide','POST',{'url':url},self.auth())[0],[URL,other]))
  self.assertEqual(results,[200,200]);entries=d.load_dashboard()['prs']
  self.assertTrue(entries[URL]['hidden']);self.assertTrue(entries[other]['hidden'])

 def test_valid_mutation_and_reload_state(self):
  self.assertEqual(self.request('/hide','POST',{'url':URL},self.auth())[0],200)
  state=json.loads(self.request('/api/state')[2]);self.assertTrue(state['prs'][0]['hidden'])
  self.assertEqual(self.request('/unhide','POST',{'url':URL},self.auth())[0],200)
 def test_host_header_and_cross_site_state_rejected(self):
  self.assertEqual(self.request('/api/state',headers={'Host':'evil.example'})[0],403)
  self.assertEqual(self.request('/api/state',headers={'Origin':'null'})[0],403)
  self.assertEqual(self.request('/api/state',headers={'Sec-Fetch-Site':'cross-site'})[0],403)
 def test_page_has_token_assets_and_no_cache(self):
  code,headers,body=self.request('/');self.assertEqual(code,200);self.assertIn(self.server.csrf_token.encode(),body);self.assertEqual(headers['Cache-Control'],'private, no-cache')
  self.assertEqual(self.request('/api/state')[1]['Cache-Control'],'no-store')
  self.assertEqual(self.request('/assets/dashboard.js')[0],200)
 def test_cancelled_response_does_not_raise_a_server_traceback(self):
  class Closed:
   def write(self,_):raise BrokenPipeError
  handler=s.Handler.__new__(s.Handler);handler.wfile=Closed()
  handler.send_response=lambda *_:None;handler.send_header=lambda *_:None;handler.end_headers=lambda:None
  handler._send(200,b'asset','text/css')
 def test_html_is_sandboxed_and_symlink_escape_rejected(self):
  p=self.root/'example.html';p.write_text('<script>fetch("/api/state")</script>')
  code,headers,_=self.request('/artifact?path='+str(p));self.assertEqual(code,200);self.assertIn('sandbox allow-scripts',headers['Content-Security-Policy']);self.assertNotIn('allow-same-origin',headers['Content-Security-Policy'])
  with tempfile.TemporaryDirectory() as other:
   secret=Path(other)/'outside.md';secret.write_text('outside');(self.root/'link.md').symlink_to(secret)
   self.assertEqual(self.request('/artifact?path='+str(self.root/'link.md'))[0],404)
 def test_local_html_links_use_the_artifact_viewer(self):
  note=self.root/'notes with spaces.md';note.write_text('notes')
  page=self.root/'local-links.html';page.write_text('<a href="'+note.as_uri()+'">Notes</a>')
  code,headers,body=self.request('/artifact?path='+str(page))
  self.assertEqual(code,200);self.assertIn(b'/artifact?path=',body);self.assertNotIn(b'file://',body)

 def test_standalone_review_offers_workspace_entry_point(self):
  page=self.root/'review.html';page.write_text('<a href="https://github.com/example/repo/pull/1">Open pull request</a><section id="review-findings"><h2>Review findings</h2><details class="review-finding"><summary>P2 · Fixture finding</summary><section class="review-comment">Draft comment</section></details></section>')
  code,headers,body=self.request('/artifact?path='+str(page))
  self.assertEqual(code,200)
  self.assertIn(b'Ask AI or post a finding in workspace',body)
  self.assertIn(b'Ask AI about this finding',body)
  self.assertIn(b'Post draft in workspace',body)
  self.assertIn(b'id="finding-1"',body)
  self.assertIn(b'/workspace?url=https%3A%2F%2Fgithub.com%2Fexample%2Frepo%2Fpull%2F1&amp;tab=review',body)
  self.assertIn(b'finding=finding-1&amp;finding_action=ask',body)
  self.assertIn(b'finding=finding-1&amp;finding_action=post',body)
  self.assertIn("connect-src 'none'",headers['Content-Security-Policy'])
  self.assertIn('allow-popups-to-escape-sandbox',headers['Content-Security-Policy'])

 def test_guided_context_is_forwarded_without_browser_text(self):
  context={'notes':['note-context-1'],'conversations':['11111111-1111-1111-1111-111111111111']}
  with patch.object(s.runtime,'start_launch',return_value={'run_id':'context-run'}) as launch:
   code,_,body=self.request('/regenerate-review','POST',{'url':URL,'guidance':'Focus','workspace_context':context},self.auth())
  self.assertEqual(code,202);self.assertEqual(json.loads(body),{'run_id':'context-run'})
  self.assertEqual(launch.call_args.kwargs['workspace_context'],context)

 def test_launch_http_roundtrip_deduplicates(self):
  with patch.object(r.reviews,'start') as launch:
   first=json.loads(self.request('/regenerate-review','POST',{'url':URL},self.auth())[2]);second=json.loads(self.request('/regenerate-review','POST',{'url':URL},self.auth())[2])
   self.assertEqual(first['run_id'],second['run_id']);self.assertEqual(launch.call_count,1)
  run=first['run_id'];self.artifact(run);self.complete(run)
  state=json.loads(self.request('/api/state')[2]);self.assertIn('review-markdown',state['prs'][0]['artifacts'])

if __name__=='__main__':unittest.main()


class Authors(Isolated):
 def test_search_bot_login_and_list_bot_login_share_profile(self):
  with patch.object(d,'fetch_author_profile',return_value={'author_name':'Renovate','author_avatar_url':'https://avatars.githubusercontent.com/in/2740'}) as fetch:
   result=d.author_profiles({'app/renovate','renovate[bot]'}, {})
  fetch.assert_called_once_with('renovate[bot]')
  self.assertEqual(list(result),['renovate[bot]'])
 def test_recent_profile_is_cached_and_failed_update_keeps_old_profile(self):
  profile={'author_name':'Someone','checked_at':d.time.time()}
  with patch.object(d,'fetch_author_profile',return_value={}) as fetch:
   self.assertEqual(d.author_profiles({'someone'},{'someone':profile})['someone'],profile)
   fetch.assert_not_called()
   profile['checked_at']=1
   self.assertEqual(d.author_profiles({'someone'},{'someone':profile})['someone'],profile)
   fetch.assert_called_once_with('someone')
 def test_snapshot_normalizes_legacy_bot_and_uses_cached_profile(self):
  data=d.load_dashboard();data['prs'][URL]['author_login']='app/renovate'
  data['author_profiles']={'renovate[bot]':{'author_name':'Renovate','author_avatar_url':'https://avatars.githubusercontent.com/in/2740'}}
  d.save_dashboard(data)
  pr=r.snapshot()['prs'][0]
  self.assertEqual(pr['author_login'],'renovate[bot]');self.assertEqual(pr['author_name'],'Renovate')
  self.assertEqual(pr['author_avatar_url'],'https://avatars.githubusercontent.com/in/2740')
 def test_refresh_retains_author_metadata_and_individual_hiding(self):
  with patch.object(d,'fetch_author_profile',return_value={'author_name':'Someone'}):
   self.refresh(lambda reason:[ITEM] if reason=='review-requested' else [])
  data=d.load_dashboard();self.assertEqual(data['author_profiles']['someone']['author_name'],'Someone')
  self.assertTrue(data['prs'][URL]['starred']);self.assertFalse(data['prs'][URL]['hidden'])

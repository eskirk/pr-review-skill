"""Personal commitments survive discovery changes and acknowledge only seen work."""
import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace as NS

import dashboard_queue as q
import dashboard_runtime as runtime
import pr_dashboard as dashboard
import pr_review_tracker as tracker
import test_dashboard as existing
URL, ENTRY = existing.URL, existing.ENTRY

A='a'*40
B='b'*40
C='c'*40
T0='2026-09-01T10:00:00Z'
T1='2026-09-01T11:00:00Z'
T2='2026-09-01T12:00:00Z'
T3='2026-09-01T13:00:00Z'


class Queue(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.env=patch.dict(os.environ,{'PR_REVIEW_TRACKER_HOME':self.tmp.name});self.env.start();self.addCleanup(self.env.stop)
  self.options=patch.object(dashboard,'discover_claude_options',return_value=([],[]));self.options.start();self.addCleanup(self.options.stop)
  dashboard.save_dashboard({'prs':{URL:{**ENTRY,'head_sha':A,'my_review_at':T0}}})
  with patch.object(tracker,'utc_now',return_value=T0):q.mutate(URL,'enqueue')
  self.fetch(A,T1)
 def record(self):return q.load()['prs'][URL]
 def view(self):return q.presentation(self.record())
 def action(self,action,**kwargs):
  return q.mutate(URL,action,{'revision':self.record()['revision'],'observed':self.view()['observed'],**kwargs})
 def fetch(self,sha,at,events=None,latest=None,closed=False):
  q.apply_fetch(URL,{'metadata':{'owner':'example','repository':'repo','number':1,'title':'Example',
      'head_sha':sha,'pr_state':'closed' if closed else 'open'},'events':events or [],'latest_review':latest or {}},at)
 def event(self,kind='reply',at=T2,id='thread:1'):
  return {'kind':kind,'at':at,'id':id,'url':URL+'#discussion_r1'}
 def test_saved_pr_survives_discovery_removal_and_stays_out_of_watching(self):
  dashboard.save_dashboard({'prs':{}})
  pr=runtime.snapshot()['prs'][0]
  self.assertEqual(pr['url'],URL);self.assertFalse(pr['discovered']);self.assertEqual(pr['workflow']['stage'],'up_next')
 def test_pasted_url_outside_discovery_and_reload(self):
  url='https://github.com/elsewhere/new/pull/123'
  q.mutate(url,'enqueue');pr=next(p for p in runtime.snapshot()['prs'] if p['url']==url)
  self.assertEqual(pr['number'],123);self.assertEqual(pr['workflow']['stage'],'up_next')
  self.assertTrue(q.mutate(url,'enqueue')['existing'])
 def test_human_review_baseline_survives_commit_arriving_mid_review(self):
  self.action('start');self.fetch(B,T2);self.action('wait')
  self.assertEqual(self.record()['ack_head'],A);self.assertEqual(self.view()['bucket'],'attention')
  self.action('acknowledge');self.assertEqual(self.view()['bucket'],'waiting')
  self.fetch(C,T3);self.assertEqual(self.view()['bucket'],'attention')
 def test_stop_returns_to_up_next_without_acknowledging_updates(self):
  self.action('note',note='Check retries');self.action('start')
  self.fetch(B,T2,[self.event()]);before=self.record()
  self.action('stop')
  self.assertEqual(self.view()['bucket'],'up_next')
  self.assertNotIn('review_observation',self.record())
  for key in ('ack_head','ack_at','ack_event_ids','note'):
   self.assertEqual(self.record().get(key),before.get(key))
  self.assertTrue(self.view()['reasons'])
  self.assertEqual(self.view()['moved']['kind'],'paused')
  self.action('start')
  self.assertEqual(self.record()['review_observation']['head_sha'],B)
 def test_pause_returns_to_top_of_up_next(self):
  second='https://github.com/example/repo/pull/2';q.mutate(second,'enqueue')
  self.action('start');self.action('stop')
  self.assertLess(self.record()['position'],q.load()['prs'][second]['position'])
 def test_every_move_records_its_reason_and_can_be_undone(self):
  self.assertEqual(self.view()['moved']['kind'],'added')
  for action,kind,bucket in [('start','started','reviewing'),('wait','handed_back','waiting'),('remove','removed','removed'),('restore','restored','up_next')]:
   before=copy.deepcopy(self.record());result=self.action(action)
   self.assertEqual(self.view()['moved']['kind'],kind);self.assertEqual(self.view()['bucket'],bucket)
   self.action('undo',revision=result['revision'],token=result['undo_token'])
   for key in q.UNDO_KEYS:self.assertEqual(self.record().get(key),before.get(key),(action,key))
   self.action(action)
 def test_undo_restores_acknowledged_updates(self):
  self.action('start');self.action('wait');self.fetch(B,T3,[self.event()])
  self.assertEqual(self.view()['bucket'],'attention')
  result=self.action('acknowledge');self.assertEqual(self.view()['bucket'],'waiting');self.assertEqual(self.view()['moved']['kind'],'kept_waiting')
  self.action('undo',revision=result['revision'],token=result['undo_token'])
  self.assertEqual(self.view()['bucket'],'attention')
 def test_stale_undo_is_rejected_after_a_newer_choice(self):
  result=self.action('start');self.action('wait')
  with self.assertRaises(dashboard.DashboardError):self.action('undo',revision=result['revision'],token=result['undo_token'])
  self.assertEqual(self.view()['bucket'],'waiting')
 def test_resuming_from_waiting_is_recorded_as_resumed(self):
  self.action('start');self.action('wait');self.action('start')
  self.assertEqual(self.view()['moved']['kind'],'resumed')
 def test_reminder_brings_a_waiting_pr_back_when_due(self):
  with self.assertRaises(dashboard.DashboardError):self.action('remind',days=3)
  self.action('start');self.action('wait')
  for days in (2,True,'3',None):
   with self.assertRaises(dashboard.DashboardError):self.action('remind',days=days)
  with patch.object(tracker,'utc_now',return_value=T1):self.action('remind',days=1)
  self.assertEqual(self.record()['remind_at'],'2026-09-02T11:00:00+00:00')
  with patch.object(tracker,'utc_now',return_value='2026-09-02T10:59:00Z'):self.assertEqual(self.view()['bucket'],'waiting')
  with patch.object(tracker,'utc_now',return_value='2026-09-02T11:00:00Z'):
   self.assertEqual(self.view()['bucket'],'attention');self.assertEqual(self.view()['reasons'][-1]['kind'],'reminder')
   self.assertEqual(self.view()['reasons'][-1]['url'],'https://github.com/example/repo/pull/1')
   self.action('acknowledge')
  self.assertNotIn('remind_at',self.record());self.assertEqual(self.view()['bucket'],'waiting')
 def test_reminder_can_be_cleared_and_is_dropped_when_review_resumes(self):
  self.action('start');self.action('wait');self.action('remind',days=7);self.action('remind',days=0)
  self.assertNotIn('remind_at',self.record())
  self.action('remind',days=3);self.action('start');self.assertNotIn('remind_at',self.record())
 def test_snooze_sets_aside_up_next_until_due(self):
  for days in (2,True,'3',None):
   with self.assertRaises(dashboard.DashboardError):self.action('snooze',days=days)
  with self.assertRaises(dashboard.DashboardError):self.action('snooze',days=0)
  with patch.object(tracker,'utc_now',return_value=T1):result=self.action('snooze',days=1)
  self.assertEqual(self.record()['snoozed_until'],'2026-09-02T11:00:00+00:00')
  self.assertEqual(self.view()['moved']['kind'],'snoozed');self.assertEqual(self.view()['stage'],'up_next')
  with patch.object(tracker,'utc_now',return_value='2026-09-02T10:59:00Z'):self.assertEqual(self.view()['bucket'],'snoozed')
  with patch.object(tracker,'utc_now',return_value='2026-09-02T11:00:00Z'):
   self.assertEqual(self.view()['bucket'],'attention');self.assertEqual(self.view()['reasons'][-1]['kind'],'snooze')
   self.assertEqual(self.view()['reasons'][-1]['url'],'https://github.com/example/repo/pull/1')
  self.action('undo',revision=result['revision'],token=result['undo_token'])
  self.assertNotIn('snoozed_until',self.record());self.assertEqual(self.view()['bucket'],'up_next')
 def test_snooze_ends_early_on_new_activity_only(self):
  self.fetch(A,T2,[self.event()])
  self.assertTrue(self.view()['reasons'])
  self.action('snooze',days=3)
  # Updates that arrived before the snooze do not end it.
  self.fetch(A,T3,[self.event()]);self.assertEqual(self.view()['bucket'],'snoozed')
  self.fetch(A,T3,[self.event(),self.event(kind='mention',at=T3,id='comment:2')])
  self.assertEqual(self.view()['bucket'],'attention')
  self.assertNotIn('snooze',[r['kind'] for r in self.view()['reasons']])
  self.action('snooze',days=1);self.assertEqual(self.view()['bucket'],'snoozed')
  self.fetch(B,T3,[self.event(),self.event(kind='mention',at=T3,id='comment:2')])
  self.assertEqual(self.view()['bucket'],'attention')
  self.action('snooze',days=0)
  self.assertNotIn('snoozed_until',self.record());self.assertEqual(self.view()['bucket'],'up_next')
  self.assertEqual(self.view()['moved']['kind'],'unsnoozed')
 def test_snoozed_review_continues_at_its_starting_commit(self):
  self.action('start');self.action('snooze',days=7)
  self.assertEqual(self.view()['bucket'],'snoozed');self.assertEqual(self.view()['stage'],'reviewing')
  self.fetch(B,T3);self.assertEqual(self.view()['bucket'],'attention')
  self.action('start')
  self.assertEqual(self.view()['bucket'],'reviewing');self.assertEqual(self.record()['review_observation']['head_sha'],A)
  self.assertNotIn('snoozed_until',self.record());self.assertNotIn('snooze_baseline',self.record())
 def test_snooze_is_for_your_turn_and_cleared_by_moves(self):
  self.action('start');self.action('wait')
  with self.assertRaises(dashboard.DashboardError):self.action('snooze',days=1)
  for action in ('start','stop','remove'):
   if action=='remove':self.action('restore')
   self.action('snooze',days=1) if self.record()['stage'] in q.SNOOZABLE else None
   self.action(action)
   self.assertNotIn('snoozed_until',self.record(),action)
  self.action('restore')
  with patch.object(tracker,'utc_now',return_value=T1):self.action('start');self.action('snooze',days=1)
  # Submitting a review on GitHub hands the PR back and ends the snooze.
  self.fetch(B,T3,latest={'commit_id':B,'submitted_at':T2,'state':'APPROVED'})
  self.assertEqual(self.view()['bucket'],'waiting');self.assertNotIn('snoozed_until',self.record())
 def test_github_review_move_is_explained(self):
  with patch.object(tracker,'utc_now',return_value=T1):self.action('start')
  self.fetch(B,T3,latest={'commit_id':B,'submitted_at':T2,'state':'APPROVED'})
  self.assertEqual(self.view()['moved'],{'kind':'github_review','at':T2})
 def test_stop_requires_reviewing_stage(self):
  with self.assertRaises(dashboard.DashboardError):self.action('stop')
 def test_resume_moves_to_reviewing_and_preserves_pending_updates(self):
  self.action('start');self.action('wait');self.fetch(B,T2,[self.event()])
  self.assertEqual(self.view()['bucket'],'attention')
  before=self.record();reasons=self.view()['reasons']
  self.action('start')
  self.assertEqual(self.view()['bucket'],'reviewing')
  self.assertEqual(self.view()['reasons'],reasons)
  for key in ('ack_head','ack_at','ack_event_ids'):
   self.assertEqual(self.record().get(key),before.get(key))
  self.assertEqual(runtime.snapshot()['prs'][0]['workflow']['bucket'],'reviewing')
  self.fetch(C,T3,[self.event(),self.event(at=T3,id='thread:2')])
  self.assertEqual(self.view()['bucket'],'reviewing')
  self.action('wait')
  self.assertEqual(self.record()['ack_head'],B)
  self.assertEqual(self.view()['bucket'],'attention')
  self.assertEqual({r['kind'] for r in self.view()['reasons']},{'head','reply'})
 def test_resumed_review_without_new_updates_returns_to_waiting(self):
  self.action('wait');self.fetch(B,T2,[self.event()]);self.action('start')
  self.assertEqual(self.view()['bucket'],'reviewing')
  self.action('wait')
  self.assertEqual(self.view()['bucket'],'waiting')
  self.assertEqual(self.view()['reasons'],[])
 def test_open_and_local_snapshot_do_not_acknowledge(self):
  self.action('start');self.action('wait');self.fetch(B,T2)
  for _ in range(3):runtime.snapshot()
  self.assertEqual(self.view()['bucket'],'attention')
 def test_stale_ui_ack_keeps_newer_commits_and_replies(self):
  self.action('start');self.action('wait');seen=self.view()['observed']
  self.fetch(B,T3,[self.event()]);self.action('acknowledge',observed=seen)
  self.assertEqual({r['kind'] for r in self.view()['reasons']},{'head','reply'})
 def test_reply_without_code_change_and_no_duplicate_after_ack(self):
  self.action('start');self.action('wait');events=[self.event()];self.fetch(A,T3,events)
  self.assertEqual(self.view()['bucket'],'attention');self.action('acknowledge')
  self.fetch(A,T3,events);self.assertEqual(self.view()['bucket'],'waiting')
 def test_unseen_reply_in_same_second_as_observation_still_returns(self):
  self.action('start');self.action('wait');seen=self.view()['observed']
  self.fetch(A,T2,[self.event(at=T1)]);self.action('acknowledge',observed=seen)
  self.assertEqual(self.view()['bucket'],'attention')
  self.action('acknowledge');self.assertEqual(self.view()['bucket'],'waiting')
 def test_removal_survives_refresh_and_undo(self):
  result=self.action('remove');self.fetch(B,T3,[self.event()])
  self.assertEqual(self.view()['bucket'],'removed');self.assertEqual(self.record()['metadata']['head_sha'],B)
  self.action('undo',token=result['undo_token']);self.assertEqual(self.view()['bucket'],'up_next')
 def test_legacy_done_action_waits_and_returns_for_replies(self):
  with patch.object(tracker,'utc_now',return_value=T1):self.action('done')
  self.fetch(B,T3,[self.event()]);self.assertEqual(self.view()['bucket'],'attention')
  self.fetch(B,T3,[self.event('requested')]);self.assertEqual(self.view()['bucket'],'attention')
  self.action('start');self.action('wait');self.assertEqual(self.view()['bucket'],'waiting')
 def test_error_retains_item_and_closed_requires_confirmed_fetch(self):
  q.apply_fetch(URL,None,T2,'Access denied');self.assertEqual(self.view()['bucket'],'up_next');self.assertEqual(self.view()['error'],'Access denied')
  self.fetch(A,T3,closed=True);self.assertEqual(self.view()['bucket'],'history');self.assertFalse(self.view()['error'])
 def test_concurrent_note_and_refresh_preserved(self):
  self.action('note',note='Check retry on reconnect');self.fetch(B,T2)
  self.assertEqual(self.record()['note'],'Check retry on reconnect')
 def test_stale_note_cannot_overwrite_newer_choice(self):
  revision=self.record()['revision'];self.action('note',note='New note')
  with self.assertRaises(dashboard.DashboardError):self.action('note',revision=revision,note='Stale note')
  self.assertEqual(self.record()['note'],'New note')
 def test_preferences_from_discovery_stay_current(self):
  data=dashboard.load_dashboard();data['prs'][URL].update(starred=False,hidden=True);dashboard.save_dashboard(data)
  pr=runtime.snapshot()['prs'][0];self.assertFalse(pr['starred']);self.assertTrue(pr['hidden']);self.assertEqual(pr['workflow']['bucket'],'up_next')
 def test_submitted_review_acknowledges_its_commit_not_latest_head(self):
  with patch.object(tracker,'utc_now',return_value=T1):self.action('start')
  self.fetch(B,T3,latest={'commit_id':A,'submitted_at':T2,'state':'COMMENTED'})
  self.assertEqual(self.record()['stage'],'waiting');self.assertEqual(self.record()['ack_head'],A)
  self.assertEqual(self.view()['bucket'],'attention')
 def test_ai_completion_does_not_complete_human_obligation(self):
  run=tracker.command_start(NS(pr_url=URL,tool='codex',title='Example',working_directory=self.tmp.name,session_reference='',base_sha='',head_sha=A),emit=False)
  for task in tracker.DEFAULT_TASKS:tracker.command_set_task(NS(run_id=run,task=task,status='completed',message=''))
  self.assertEqual(runtime.snapshot()['prs'][0]['workflow']['stage'],'up_next')
 def test_ordering_and_restoration(self):
  second='https://github.com/example/repo/pull/2';q.mutate(second,'enqueue')
  r=q.load()['prs'][second];q.mutate(second,'move_up',{'revision':r['revision']})
  self.assertLess(q.load()['prs'][second]['position'],self.record()['position'])
 def test_history_discovery_is_automatic_but_does_not_enroll_active_work(self):
  import dashboard_reporting as reporting
  candidate={'url':'https://github.com/other/repo/pull/2','title':'Candidate','state':'OPEN',
   'closedAt':None,'mergedAt':None,'createdAt':T0,'updatedAt':T3,'isDraft':False,
   'headRefOid':A,'baseRefOid':B,'author':{'login':'other'}}
  result={'search':{'issueCount':1,'nodes':[candidate],'pageInfo':{'hasNextPage':False,'endCursor':None}}}
  with patch.object(reporting,'graphql',return_value=result) as search:q.discover_history('me',T3)
  record=q.load()['prs'][candidate['url']]
  self.assertEqual(record['stage'],'waiting');self.assertFalse(q.presentation(record)['in_history'])
  self.assertEqual(q.presentation(record)['moved'],{'kind':'discovered','at':T3})
  self.assertEqual(self.record()['stage'],'up_next')
  self.assertEqual(search.call_count,4)
 def test_incomplete_search_preserves_history(self):
  import dashboard_reporting as reporting
  before=q.load()
  with patch.object(reporting,'graphql',return_value={'search':{'issueCount':1001}}):
   with self.assertRaises(dashboard.DashboardError):q.discover_history('me',T3)
  self.assertEqual(q.load(),before)
 def test_history_search_paginates_and_deduplicates(self):
  import dashboard_reporting as reporting
  def result(number,more=False):
   return {'search':{'issueCount':101,'nodes':[{'url':f'https://github.com/other/repo/pull/{number}',
    'title':str(number),'state':'OPEN','createdAt':T0,'updatedAt':T3,'isDraft':False,
    'headRefOid':A,'baseRefOid':B,'author':None}],
    'pageInfo':{'hasNextPage':more,'endCursor':'next' if more else None}}}
  # Searches run in parallel, so page by cursor rather than call order.
  def page(_query,variables):
   if 'reviewed-by' in variables['query'] and 'is:open' in variables['query']:
    return result(3) if variables['cursor']=='next' else result(2,True)
   return result(2)
  with patch.object(reporting,'graphql',side_effect=page) as search:
   q.discover_history('me',T3)
  self.assertEqual(len(q.load()['prs']),3)
  self.assertEqual(search.call_count,5)
  self.assertEqual(sum(call.args[1]['cursor']=='next' for call in search.call_args_list),1)
 def test_expired_search_hit_is_not_reintroduced(self):
  import dashboard_reporting as reporting
  from datetime import datetime,timedelta,timezone
  stamp=(datetime.now(timezone.utc)-timedelta(days=21)).isoformat()
  result={'search':{'issueCount':1,'nodes':[{'url':'https://github.com/other/repo/pull/2',
   'title':'Old','state':'MERGED','mergedAt':stamp,'closedAt':stamp,'createdAt':T0,
   'updatedAt':T3,'isDraft':False,'headRefOid':A,'baseRefOid':B,'author':None}],
   'pageInfo':{'hasNextPage':False,'endCursor':None}}}
  with patch.object(reporting,'graphql',return_value=result):q.discover_history('me',T3)
  self.assertEqual(len(q.load()['prs']),1)
 def test_open_participation_stays_out_of_closed_section(self):
  self.assertFalse(self.view()['in_history']);self.assertEqual(self.view()['bucket'],'up_next')
 def test_legacy_done_and_history_migrate_to_waiting(self):
  for stage in ('done','history'):
   data=q.load();data['prs'][URL]['stage']=stage;q.save(data)
   self.assertEqual(self.record()['stage'],'waiting')
   self.assertEqual(self.view()['bucket'],'waiting')
 def test_wait_from_up_next_keeps_unseen_updates(self):
  seen=self.view()['observed'];self.fetch(B,T3,[self.event()])
  self.action('wait',observed=seen)
  self.assertEqual(self.record()['stage'],'waiting')
  self.assertEqual(self.view()['bucket'],'attention')
 def test_older_fetch_cannot_replace_newer_snapshot(self):
  self.fetch(B,T3);self.fetch(A,T2);self.assertEqual(self.record()['metadata']['head_sha'],B)
 def versions(self,updated=T1,head=A,state='OPEN'):return {URL:{'updatedAt':updated,'headRefOid':head,'state':state}}
 def fetched(self,updated=T1,head=A,at=T1):
  data=q.load();record=data['prs'][URL];record.update(fetched={'updated_at':updated,'head_sha':head},checked_at=at,error='')
  record['metadata']={**record.get('metadata',{}),'additions':3,'deletions':1,'changed_files':2};q.save(data)
 def run_refresh(self,versions,full=False):
  import dashboard_retention,storage_cleanup
  payload={'metadata':{'head_sha':A,'pr_updated_at':T1,'pr_state':'open'},'events':[],'latest_review':{}}
  with patch.object(tracker,'utc_now',return_value='2026-09-01T11:30:00+00:00'),patch.object(q,'api',return_value={'login':'me'}),\
       patch.object(q,'discover_history',return_value=set()),patch.object(q,'remote_versions',return_value=versions) as remote,\
       patch.object(q,'fetch_pr',return_value=payload) as fetch,patch.object(dashboard_retention,'cleanup',return_value=[]),\
       patch.object(storage_cleanup,'maintain'):
   q.refresh(full=full)
  return remote,fetch
 def test_unchanged_open_pr_skips_detailed_fetch_until_hourly_check(self):
  self.fetched();now=q.epoch(T1)+60
  self.assertTrue(q.unchanged(self.record(),self.versions()[URL],now))
  for remote in (self.versions(updated=T2)[URL],self.versions(head=B)[URL],self.versions(state='MERGED')[URL],None):
   self.assertFalse(q.unchanged(self.record(),remote,now))
  self.assertFalse(q.unchanged(self.record(),self.versions()[URL],q.epoch(T1)+q.FULL_CHECK_SECONDS))
  data=q.load();data['prs'][URL]['error']='GitHub could not be checked.';q.save(data)
  self.assertFalse(q.unchanged(self.record(),self.versions()[URL],now))
 def test_records_saved_before_sizes_get_one_detailed_fetch(self):
  self.fetched();data=q.load();del data['prs'][URL]['metadata']['additions'];q.save(data)
  self.assertFalse(q.unchanged(self.record(),self.versions()[URL],q.epoch(T1)+60))
 def test_detailed_fetch_records_what_it_saw(self):
  q.apply_fetch(URL,{'metadata':{'head_sha':B,'pr_updated_at':T2},'events':[],'latest_review':{}},T2)
  self.assertEqual(self.record()['fetched'],{'updated_at':T2,'head_sha':B})
 def test_refresh_fetches_only_changed_prs_unless_full(self):
  self.fetched()
  _,fetch=self.run_refresh(self.versions());fetch.assert_not_called();self.assertEqual(self.record()['checked_at'],T1)
  _,fetch=self.run_refresh(self.versions(updated=T2));fetch.assert_called_once()
  self.fetched()
  remote,fetch=self.run_refresh(self.versions(),full=True);remote.assert_not_called();fetch.assert_called_once()
 def test_remote_versions_batches_and_omits_unreadable_prs(self):
  import dashboard_reporting as reporting
  urls=[f'https://github.com/example/repo/pull/{n}' for n in range(1,q.BATCH_SIZE+3)]
  def graphql(query,variables):
   if variables['n0']!=1:raise dashboard.DashboardError('Unavailable')
   return {f'p{i}':{'pullRequest':None if i==1 else {'updatedAt':T1,'headRefOid':A,'state':'OPEN'}} for i in range(q.BATCH_SIZE)}
  with patch.object(reporting,'graphql',side_effect=graphql) as call:versions=q.remote_versions(urls)
  self.assertEqual(call.call_count,2)
  self.assertEqual(set(versions),set(urls[:q.BATCH_SIZE])-{urls[1]})
 def wait_until(self,condition):
  import time
  deadline=time.time()+2
  while not condition():
   self.assertLess(time.time(),deadline);time.sleep(0.01)
 def test_single_pr_check_skips_untracked_prs_and_sync_status(self):
  data=q.load();data['login']='me';q.save(data);before=q.status();seen=[]
  def fetch(url,login):
   seen.append((url,login));return {'metadata':{'head_sha':B},'events':[],'latest_review':{}}
  with patch.object(q,'fetch_pr',side_effect=fetch),patch.object(q,'api',side_effect=AssertionError('reuse the saved login')):
   self.assertTrue(q.start_fetch([URL,URL,'https://github.com/other/repo/pull/9']))
   self.assertFalse(q.start_fetch(['https://github.com/other/repo/pull/9']))
   self.wait_until(lambda:not q._fetching)
  self.assertEqual(seen,[(URL,'me')]);self.assertEqual(self.record()['metadata']['head_sha'],B)
  self.assertEqual(q.status(),before)
 def test_sync_during_background_refresh_runs_one_more_pass(self):
  import threading
  entered,release,calls=threading.Event(),threading.Event(),[]
  def refresh(full=False):
   calls.append(full)
   if len(calls)==1:entered.set();release.wait(2)
  with patch.object(q,'refresh',side_effect=refresh):
   self.assertTrue(q.start_refresh(force=True));self.assertTrue(entered.wait(2))
   self.assertFalse(q.status()['manual'])
   self.assertFalse(q.start_refresh(force=True,manual=True));self.assertFalse(q.start_refresh(force=True,manual=True))
   self.assertTrue(q.status()['manual']);release.set()
   self.wait_until(lambda:not q._running)
  self.assertEqual(len(calls),2);self.assertEqual(q.status()['status'],'completed');self.assertFalse(q.status()['manual'])
 def test_wrong_account_preserves_queue(self):
  data=q.load();data['login']='original';q.save(data)
  with patch.object(q,'api',return_value={'login':'other'}),patch.object(q,'fetch_pr') as fetch:
   with self.assertRaises(dashboard.DashboardError):q.refresh()
   fetch.assert_not_called()


class Classification(unittest.TestCase):
 def comment(self,id,user='author',at=T2,**extra):return {'id':id,'user':{'login':user,'type':'User'},'created_at':at,'body':'Update','html_url':URL+'#'+str(id),**extra}
 def classify(self,comments=(),discussion=(),requests=(),reviews=()):
  return q.classify(URL,'me',{'title':'PR','state':'open','head':{'sha':A},'user':{'login':'author'}},comments,discussion,requests,reviews)
 def test_only_participating_thread_replies_and_mentions(self):
  comments=[self.comment(1,'me',T0),self.comment(2,in_reply_to_id=1),self.comment(3,'someone'),self.comment(4,'me',T2,in_reply_to_id=1),self.comment(5,'bot[bot]',in_reply_to_id=1),self.comment(6,'someone',body='Please check @me')]
  events=self.classify(comments)['events'];self.assertEqual([(e['id'],e['kind']) for e in events],[('thread:2','reply'),('thread:6','mention')])
 def test_participation_as_reply_also_watches_thread(self):
  comments=[self.comment(1,'other',T0),self.comment(2,'me',T1,in_reply_to_id=1),self.comment(3,in_reply_to_id=1)]
  self.assertEqual([e['id'] for e in self.classify(comments)['events']],['thread:3'])
 def test_author_comment_after_feedback_and_direct_request(self):
  discussion=[self.comment(1,'me',T0),self.comment(2),self.comment(3,'unrelated')]
  requests=[{'id':4,'event':'review_requested','requested_reviewer':{'login':'me'},'created_at':T2}, {'id':5,'event':'labeled','created_at':T2}, {'id':6,'event':'review_requested','requested_reviewer':{'login':'other'},'created_at':T2}]
  self.assertEqual({e['kind'] for e in self.classify(discussion=discussion,requests=requests)['events']},{'author','requested'})
 def test_paginated_api_combines_all_pages_and_is_explicitly_read_only(self):
  with patch.object(q.subprocess,'run',return_value=NS(returncode=0,stdout=json.dumps([[{'id':1}],[{'id':2}]]))) as run:
   self.assertEqual(q.api('repos/example/repo/pulls/1/comments?per_page=100',True),[{'id':1},{'id':2}])
   self.assertIn('--paginate',run.call_args.args[0]);self.assertIn('GET',run.call_args.args[0])
 def test_partial_pagination_is_not_success(self):
  with patch.object(q.subprocess,'run',return_value=NS(returncode=1,stdout='[[{"id":1}]]')):
   with self.assertRaises(dashboard.DashboardError):q.api('anything',True)


class QueueHTTP(existing.HTTP):
 def test_queue_actions_require_auth_and_survive_reload(self):
  with patch.object(q,'start_fetch'):
   self.assertEqual(self.request('/queue','POST',{'url':URL,'action':'enqueue'})[0],403)
   self.assertEqual(self.request('/queue','POST',{'url':URL,'action':'enqueue'},self.auth())[0],200)
  pr=json.loads(self.request('/api/state')[2])['prs'][0]
  self.assertEqual(pr['workflow']['stage'],'up_next')
  self.assertEqual(self.request('/queue','POST',{'url':URL,'action':'note','revision':pr['workflow']['revision'],'note':'private'},self.auth())[0],200)
  self.assertEqual(q.load()['prs'][URL]['note'],'private')
 def test_saving_a_pr_checks_only_that_pr(self):
  with patch.object(q,'start_fetch') as fetch,patch.object(q,'start_refresh') as refresh:
   self.assertEqual(self.request('/queue','POST',{'url':URL,'action':'enqueue'},self.auth())[0],200)
  fetch.assert_called_once_with([URL]);refresh.assert_not_called()
 def test_targeted_queue_check_validates_urls(self):
  with patch.object(q,'start_fetch',return_value=True) as fetch:
   self.assertEqual(self.request('/refresh-queue','POST',{'urls':[URL]},self.auth())[0],202)
   for urls in ([],'x',[1],['https://evil.example/pull/1'],[URL]*51):
    self.assertEqual(self.request('/refresh-queue','POST',{'urls':urls},self.auth())[0],400)
  fetch.assert_called_once_with([URL])
 def test_sync_marks_queue_refresh_manual(self):
  with patch.object(q,'start_refresh') as refresh,patch.object(runtime,'start_refresh',return_value=True):
   self.assertEqual(self.request('/refresh','POST',{},self.auth())[0],202)
  refresh.assert_called_once_with(force=True,triage_after=True,manual=True)
 def test_refresh_and_recovery_cannot_be_triggered_cross_origin(self):
  with patch.object(q,'start_refresh') as refresh:
   for endpoint in ('/refresh-queue','/recover-reviews'):
    self.assertEqual(self.request(endpoint,'POST',{})[0],403)
   refresh.assert_not_called()
 def test_invalid_url_rejected_without_network(self):
  with patch.object(q,'start_refresh') as refresh:
   self.assertEqual(self.request('/queue','POST',{'url':'https://evil.example/pull/1','action':'enqueue'},self.auth())[0],400)
   refresh.assert_not_called()


def load_tests(loader, tests, pattern):
 suite=unittest.TestSuite([loader.loadTestsFromTestCase(Queue),loader.loadTestsFromTestCase(Classification)])
 # Reuse the HTTP fixture without rerunning all its unrelated inherited tests.
 suite.addTests(QueueHTTP(name) for name in QueueHTTP.__dict__ if name.startswith('test_'))
 return suite


if __name__=='__main__':unittest.main()

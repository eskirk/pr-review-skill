import json
import os
from argparse import Namespace
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import pr_dashboard as dashboard


class DashboardLaunch(unittest.TestCase):
    def test_checkout_discovery_uses_environment_and_current_home(self):
        with patch.dict(os.environ, {'PR_REVIEW_LOCAL_DEV_ROOT': '~/Source projects'}):
            prompt = dashboard.full_review_prompt('https://github.com/example/repo/pull/1')
            self.assertIn(str(Path('~/Source projects').expanduser()), prompt)
        with patch.dict(os.environ, {}, clear=True), \
             patch.object(Path, 'home', return_value=Path('/tmp/example-user')):
            self.assertIn('/tmp/example-user/Development', dashboard.local_checkout_hint())

    def test_review_prompt_passes_real_provider_model_and_person_for_comment_footer(self):
        import review_context
        with patch.object(review_context, 'person_name', return_value='Robert'):
            prompt = review_context.review_prompt('RUN', 'Review it', {'provider': 'codex', 'model': 'gpt-6-astra'})
            self.assertIn('"comment_attribution": {"tool": "Codex", "model": "gpt-6-astra", "person": "Robert"}', prompt)
            self.assertIn('YOUR_MODEL_ID', review_context.review_prompt('RUN', 'Review it', {'provider': 'claude', 'model': ''}))
            self.assertNotIn('comment_attribution', review_context.review_prompt('RUN', 'Review it'))
        with patch.object(review_context, 'person_name', return_value=''):
            self.assertNotIn('comment_attribution', review_context.review_prompt('RUN', 'Review it', {'provider': 'codex', 'model': 'x'}))

    def test_configured_style_skill_is_injected_as_bounded_comment_guidance(self):
        import review_context
        with tempfile.TemporaryDirectory() as directory:
            skill = Path(directory) / 'SKILL.md'
            text = '# local voice\n- keep comments lowercase\n- never use em dashes'
            skill.write_text(text, encoding='utf-8')
            with patch.dict(os.environ, {review_context.STYLE_SKILL_ENV: str(skill)}):
                resolved = review_context.style_skill_for_job()
                prompt = review_context.review_prompt('RUN', 'Review it',
                    {'style_skill': resolved['metadata']}, style=resolved)
            self.assertTrue(resolved['metadata']['applied'])
            self.assertEqual(resolved['metadata']['name'], 'my-feedback-voice')
            self.assertEqual(resolved['metadata']['path'], str(skill.resolve()))
            self.assertNotIn(text, json.dumps(resolved['metadata']))
            self.assertIn('BEGIN my-feedback-voice STYLE GUIDANCE', prompt)
            self.assertIn(text, prompt)
            self.assertIn('only to copyable GitHub review comments', prompt)
            self.assertIn('must not change review scope, severity, safety, privacy', prompt)

    def test_style_skill_falls_back_to_pi_or_agents_skill_paths(self):
        import review_context
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            skill = home / '.agents' / 'skills' / 'my-feedback-voice' / 'SKILL.md'
            skill.parent.mkdir(parents=True)
            skill.write_text('lowercase feedback', encoding='utf-8')
            with patch.dict(os.environ, {}, clear=True), patch.object(Path, 'home', return_value=home):
                resolved = review_context.style_skill_for_job()
            self.assertTrue(resolved['metadata']['applied'])
            self.assertEqual(resolved['metadata']['path'], str(skill.resolve()))
            self.assertIn('lowercase feedback', resolved['text'])

    def test_missing_style_skill_does_not_block_review_or_trigger_fallback(self):
        import review_context
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / 'missing.md'
            with patch.dict(os.environ, {review_context.STYLE_SKILL_ENV: str(missing)}):
                resolved = review_context.style_skill_for_job()
                prompt = review_context.review_prompt('RUN', 'Review it',
                    {'style_skill': resolved['metadata']}, style=resolved)
            self.assertFalse(resolved['metadata']['applied'])
            self.assertEqual(resolved['metadata']['reason'], 'unavailable')
            self.assertNotIn('BEGIN my-feedback-voice STYLE GUIDANCE', prompt)

    def test_style_skill_is_size_and_encoding_bounded(self):
        import review_context
        with tempfile.TemporaryDirectory() as directory:
            oversized = Path(directory) / 'oversized.md'
            oversized.write_bytes(b'x' * (review_context.STYLE_SKILL_MAX_BYTES + 1))
            with patch.dict(os.environ, {review_context.STYLE_SKILL_ENV: str(oversized)}):
                resolved = review_context.style_skill_for_job()
            self.assertEqual(resolved['metadata']['reason'], 'too-large')
            invalid = Path(directory) / 'invalid.md'
            invalid.write_bytes(b'\xff')
            with patch.dict(os.environ, {review_context.STYLE_SKILL_ENV: str(invalid)}):
                resolved = review_context.style_skill_for_job()
            self.assertEqual(resolved['metadata']['reason'], 'invalid-utf8')

    def test_both_providers_share_review_worker_and_keep_feature_selection(self):
        from test_dashboard import Isolated, URL
        import ai_settings
        import dashboard_runtime as runtime
        fixture=Isolated();fixture.setUp()
        try:
            for provider in ('codex','claude'):
                settings=ai_settings.load();settings['review']['provider']=provider
                ai_settings.save(settings)
                with patch.object(runtime.reviews,'start') as launch:
                    result=runtime.start_launch(URL,'review',retry=True)
                run_id,prompt,config=launch.call_args.args
                self.assertEqual(result['transport'],'in-app')
                self.assertEqual(config,ai_settings.selected('review'))
                self.assertIn(run_id,prompt)
                self.assertNotIn('launch-exit',prompt)
        finally:fixture.tearDown()

    def test_stale_legacy_run_is_recoverable_without_hiding_fresh_activity(self):
        from test_dashboard import Isolated, URL
        import dashboard_runtime as runtime
        import pr_review_tracker as tracker
        fixture = Isolated(); fixture.setUp()
        try:
            run_id = tracker.command_start(Namespace(pr_url=URL, tool='pi', title='Example',
                working_directory='', session_reference='legacy-session', base_sha='', head_sha=''), emit=False)
            tracker.command_set_task(Namespace(run_id=run_id, task='checkout', status='running', message='Working'))
            run = tracker.load_run(tracker.run_dir(run_id), 6)
            with patch.object(runtime, 'age_seconds', return_value=runtime.LEGACY_RUN_STALE_SECONDS + 1):
                self.assertEqual(runtime.summarize_run(run)['status'], 'no-activity')
                self.assertEqual(runtime.active_runs(URL, [run]), [])
            with patch.object(runtime, 'age_seconds', return_value=0):
                self.assertEqual(runtime.summarize_run(run)['status'], 'running')
                self.assertEqual(len(runtime.active_runs(URL, [run])), 1)
        finally:
            fixture.tearDown()

    def test_selected_workspace_context_is_in_prompt_and_metadata(self):
        from test_dashboard import Isolated, URL
        import workspace_chat as chat
        import workspace_store as store
        import pr_review_tracker as tracker
        import dashboard_runtime as runtime
        fixture=Isolated();fixture.setUp()
        try:
            note_id='note-context-1'
            tracker.atomic_write(store.directory(URL)/'state.json',{
                'version':0,'viewed':{},'collapsed':[],
                'notes':[{'id':note_id,'text':'Check timeout cleanup','head':'b'*40,'base':'a'*40}],
                'attachments':{}})
            thread_id='11111111-1111-1111-1111-111111111111'
            chat.save(URL,{'id':thread_id,'base':'a'*40,'head':'b'*40,'status':'completed','messages':[
                {'role':'user','text':'Focus on the timer.'},
                {'role':'assistant','text':'The timer needs cleanup.','reads':[{'kind':'read_file','path':'secret'}]}]})
            with patch.object(runtime.reviews,'start') as launch:
                run_id=runtime.start_launch(URL,'review',retry=True,workspace_context={
                    'notes':[note_id],'conversations':[thread_id]})['run_id']
            prompt=launch.call_args.args[1]
            self.assertIn('Check timeout cleanup',prompt)
            self.assertIn('Focus on the timer.',prompt)
            self.assertIn('The timer needs cleanup.',prompt)
            self.assertNotIn('read_file',prompt)
            meta=json.loads(runtime.launch_path(run_id).read_text())
            self.assertEqual(meta['workspace_context']['notes'],[note_id])
            self.assertEqual(meta['workspace_context']['conversations'],[thread_id])
            self.assertNotIn('Check timeout cleanup',json.dumps(meta))
        finally:fixture.tearDown()

    def test_guidance_steers_prompt_and_is_recorded_with_the_run(self):
        from test_dashboard import Isolated, URL
        import dashboard_runtime as runtime
        fixture=Isolated();fixture.setUp()
        try:
            with patch.object(runtime.reviews,'start') as launch:
                runtime.start_launch(URL,'review',retry=True,guidance='  Docs only; skip tests.  ')
            run_id,prompt,_=launch.call_args.args
            self.assertIn('<<<\nDocs only; skip tests.\n>>>',prompt)
            self.assertTrue(prompt.rstrip().endswith('which checks it skipped.'))
            meta=json.loads(runtime.launch_path(run_id).read_text())
            self.assertEqual(meta['guidance'],'Docs only; skip tests.')
            with patch.object(runtime.reviews,'start') as launch:
                runtime.start_launch(URL,'review',retry=True,guidance='   ')
            run_id,prompt,_=launch.call_args.args
            self.assertNotIn('Reviewer guidance',prompt)
            self.assertNotIn('Selected private review context',prompt)
            self.assertNotIn('guidance',json.loads(runtime.launch_path(run_id).read_text()))
            with self.assertRaises(dashboard.DashboardError):
                runtime.start_launch(URL,'review',retry=True,guidance='x'*(runtime.GUIDANCE_LIMIT+1))
        finally:fixture.tearDown()

    def test_deep_explanation_is_added_to_the_recorded_guidance(self):
        from test_dashboard import Isolated, URL
        import dashboard_runtime as runtime
        fixture=Isolated();fixture.setUp()
        try:
            for guidance,expected in (('',runtime.DEEP_EXPLANATION),('Docs only.','Docs only.\n'+runtime.DEEP_EXPLANATION)):
                with patch.object(runtime.reviews,'start') as launch:
                    runtime.start_launch(URL,'review',retry=True,guidance=guidance,deep_explanation=True)
                run_id,prompt,_=launch.call_args.args
                self.assertIn('<<<\n'+expected+'\n>>>',prompt)
                self.assertEqual(json.loads(runtime.launch_path(run_id).read_text())['guidance'],expected)
        finally:fixture.tearDown()


if __name__ == '__main__':
    unittest.main()

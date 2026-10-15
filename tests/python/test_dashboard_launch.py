import json
import os
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


if __name__ == '__main__':
    unittest.main()

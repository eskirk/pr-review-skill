import json
from unittest.mock import patch
from urllib.parse import urlencode
import test_dashboard
import workspace_github as github
import workspace_chat as chat
import code_workspace as workspace
from test_code_workspace import manifest, URL, REV


class WorkspaceHTTP(test_dashboard.HTTP):
    def test_workspace_routes_are_origin_checked_and_save_is_csrf_protected(self):
        comparison=manifest()
        query='?'+urlencode({'url':URL})
        with patch.object(github,'manifest',return_value=comparison),patch.object(workspace,'review',return_value={'artifact':None,'run':None}):
            self.assertEqual(self.request('/api/workspace'+query,headers={'Origin':'https://evil.example'})[0],403)
            code,_,body=self.request('/api/workspace'+query)
            self.assertEqual(code,200);state=json.loads(body)['saved']
            request={'url':URL,'revision':REV,'version':state['version'],'viewed':[],'collapsed':[],'notes':[]}
            with patch.object(github,'cached',return_value=comparison):
                self.assertEqual(self.request('/workspace-save','POST',request)[0],403)
                self.assertEqual(self.request('/workspace-save','POST',request,self.auth())[0],200)
                self.assertEqual(self.request('/workspace-save','POST',request,self.auth())[0],400)
            self.assertEqual(self.request('/workspace')[0],200)
            self.assertEqual(self.request('/assets/code-workspace/model.mjs')[0],200)
            self.assertEqual(self.request('/assets/code-workspace/progress.mjs')[0],200)
            for asset in ('chat-markdown.mjs','chat-resize.mjs','vendor/markdown-it.mjs'):
                self.assertEqual(self.request('/assets/code-workspace/'+asset)[0],200)
            self.assertEqual(self.request('/assets/code-workspace/../../SKILL.md')[0],404)

    def test_private_context_endpoint_is_origin_checked(self):
        query='?'+urlencode({'url':URL,'head':'b'*40})
        self.assertEqual(self.request('/api/workspace-context'+query,headers={'Origin':'https://evil.example'})[0],403)
        code,_,body=self.request('/api/workspace-context'+query)
        self.assertEqual(code,200)
        value=json.loads(body)
        self.assertEqual(value['notes'],[])
        self.assertEqual(value['conversations'],[])
        self.assertIn('max_chars',value['limits'])

    def test_embedded_report_retains_opaque_sandbox(self):
        report=self.root/'report.html';report.write_text('<h1>Review</h1>')
        with patch.object(workspace,'review',return_value={'artifact':{'path':str(report),'version':'v1'}}):
            code,headers,body=self.request('/workspace-report?'+urlencode({'url':URL,'version':'v1'}))
            self.assertEqual(code,200)
            csp=headers['Content-Security-Policy']
            self.assertIn("frame-ancestors 'self'",csp)
            self.assertIn('sandbox allow-scripts',csp)
            self.assertNotIn('allow-same-origin',csp)
            self.assertIn(b'workspace-report-theme',body)
            self.assertIn(b'workspace-report-size',body)
            self.assertIn(b'workspace-report-style',body)
            self.assertEqual(self.request('/workspace-report?'+urlencode({'url':URL,'version':'old'}))[0],404)

    def test_new_chat_profile_refresh_is_origin_guarded(self):
        import ai_settings
        self.assertEqual(self.request('/api/workspace-ai',headers={'Origin':'https://example.com'})[0],403)
        self.assertEqual(json.loads(self.request('/api/workspace-ai')[2]),ai_settings.selected('chat'))
        settings=ai_settings.load();settings['chat']['provider']='claude';ai_settings.save(settings)
        self.assertEqual(json.loads(self.request('/api/workspace-ai')[2])['provider'],'claude')

    def test_chat_mutation_is_not_available_to_cross_origin(self):
        with patch.object(chat,'start',return_value={'id':'new'}) as start:
            self.assertEqual(self.request('/workspace-chat','POST',{'url':URL})[0],403)
            start.assert_not_called()
            self.assertEqual(self.request('/workspace-chat','POST',{'url':URL},self.auth())[0],202)

    def test_load_progress_is_polled_during_load_and_cleared_after(self):
        import workspace_progress
        seen=[]
        def load(url,progress=None):
            progress('Listing changed files',2,9,title='Test PR')
            seen.append(json.loads(self.request('/api/workspace-progress?'+urlencode({'url':URL,'load':'load-1234'}))[2]))
            return manifest()
        with patch.object(github,'manifest',side_effect=load),patch.object(workspace,'review',return_value={'artifact':None,'run':None}):
            self.assertEqual(self.request('/api/workspace?'+urlencode({'url':URL,'load':'load-1234'}))[0],200)
        self.assertEqual(seen,[{'step':'Listing changed files','done':2,'total':9,'title':'Test PR'}])
        self.assertEqual(workspace_progress.snapshot('load-1234'),{'step':None,'done':0,'total':None})
        self.assertIsNone(workspace_progress.reporter('../bad id'))

    def test_saved_report_lookup_survives_github_failure(self):
        query='?'+urlencode({'url':URL})
        report={'artifact':{'path':'/tmp/saved.html','version':'v1'},'run':None}
        with patch.object(github,'manifest',side_effect=ValueError('GitHub unavailable')),patch.object(workspace,'review',return_value=report):
            self.assertEqual(self.request('/api/workspace'+query)[0],400)
            code,_,body=self.request('/api/workspace-review'+query)
            self.assertEqual(code,200)
            self.assertEqual(json.loads(body),report)

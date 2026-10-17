"""Saved reader familiarity, atomic settings boundaries and shared provider prompts."""
import copy
import json

import ai_settings
import pr_dashboard as dashboard
import pr_review_tracker as tracker
import review_context
from test_dashboard import HTTP, Isolated, URL


class ReaderFamiliarity(Isolated):
    def save_repositories(self, repositories):
        settings = ai_settings.load()
        settings['known_repositories'] = repositories
        return ai_settings.save(settings, ai_settings.revision(ai_settings.load()))

    def test_existing_settings_migrate_without_writing(self):
        self.assertEqual(ai_settings.load()['known_repositories'], [])
        legacy = ai_settings.load()
        del legacy['known_repositories']
        tracker.atomic_write(dashboard.config_path(), {'ai': legacy})
        before = dashboard.config_path().read_bytes()
        self.assertEqual(ai_settings.load()['known_repositories'], [])
        self.assertEqual(dashboard.config_path().read_bytes(), before)

    def test_normalizes_persists_deduplicates_and_clears(self):
        dashboard.add_watched_repo('other/watched')
        before = ai_settings.load()
        result = self.save_repositories([' Example/Repo ', 'example/REPO', 'another/repo.name'])
        saved = ai_settings.load()
        self.assertEqual(saved['known_repositories'], ['example/repo', 'another/repo.name'])
        self.assertEqual(result['revision'], ai_settings.revision(saved))
        self.assertEqual(result['settings'], saved)
        self.assertEqual(dashboard.load_config()['watched_repos'], ['other/watched'])
        for feature in ('review', 'triage', 'chat'):
            self.assertEqual(saved[feature], before[feature])
        ai_settings.configure_triage({'daily_limit': 25})
        self.assertEqual(ai_settings.load()['known_repositories'], saved['known_repositories'])
        self.save_repositories([])
        self.assertEqual(ai_settings.load()['known_repositories'], [])

    def test_invalid_entries_do_not_save_any_settings(self):
        self.save_repositories(['example/repo'])
        before = dashboard.config_path().read_bytes()
        invalid = [None, 'example/repo', {}, [None], [''], ['owner/*'],
                   ['https://github.com/owner/repo'], ['owner/repo/pull/1'],
                   ['owner/repo\nother/repo'], ['-owner/repo'], ['owner/..'],
                   ['owner/.'], ['owner/repo name'], ['a' * 40 + '/repo'],
                   ['owner/' + 'a' * 101], [f'owner/repo{i}' for i in range(201)]]
        for values in invalid:
            with self.subTest(values=values):
                settings = ai_settings.load()
                settings['chat']['provider'] = 'claude'
                settings['known_repositories'] = values
                with self.assertRaises(ValueError):
                    ai_settings.save(settings)
                self.assertEqual(dashboard.config_path().read_bytes(), before)
        self.save_repositories([f'owner/repo{i}' for i in range(200)])
        self.assertEqual(len(ai_settings.load()['known_repositories']), 200)

    def test_familiarity_and_provider_edits_share_revision_protection(self):
        stale = ai_settings.load()
        revision = ai_settings.revision(stale)
        self.save_repositories(['example/repo'])
        stale['review']['provider'] = 'codex'
        with self.assertRaisesRegex(ValueError, 'another window'):
            ai_settings.save(stale, revision)
        self.assertEqual(ai_settings.load()['known_repositories'], ['example/repo'])
        stale = copy.deepcopy(ai_settings.load())
        revision = ai_settings.revision(stale)
        changed = copy.deepcopy(stale)
        changed['chat']['provider'] = 'claude'
        ai_settings.save(changed, ai_settings.revision(stale))
        stale['known_repositories'] = ['other/repo']
        with self.assertRaisesRegex(ValueError, 'another window'):
            ai_settings.save(stale, revision)

    def test_full_update_and_legacy_copy_prompts_include_familiarity(self):
        for builder in (dashboard.full_review_prompt, dashboard.update_review_prompt, dashboard.explainer_prompt):
            self.save_repositories([])
            self.assertIn('Reader familiarity: new', builder(URL).splitlines())
            self.save_repositories(['EXAMPLE/REPO'])
            prompt = builder(URL)
            self.assertIn('Reader familiarity: familiar', prompt.splitlines())
            self.assertIn('references/explanation.md', prompt)
            self.assertIn('Reader familiarity: new', builder('https://github.com/other/repo/pull/1').splitlines())

    def test_provider_wrapper_uses_run_repository_and_defaults_to_new(self):
        self.save_repositories(['EXAMPLE/REPO'])
        run_id = self.create_run()
        for provider in ('claude', 'codex'):
            for prompt in ('Review this PR', dashboard.full_review_prompt(URL), dashboard.update_review_prompt(URL)):
                wrapped = review_context.review_prompt(run_id, prompt, {'provider': provider}, style={})
                self.assertIn('Reader familiarity: familiar', wrapped.splitlines())
                self.assertEqual(wrapped.count('Reader familiarity:'), 1)
                self.assertIn('references/explanation.md', wrapped)
        self.assertIn('Reader familiarity: new', review_context.review_prompt('UNKNOWN', 'Review it', style={}).splitlines())


class ReaderFamiliarityHTTP(HTTP):
    def test_save_validation_reload_and_stale_revision(self):
        settings = ai_settings.load()
        settings['known_repositories'] = ['Example/Repo']
        payload = {'settings': settings, 'revision': ai_settings.revision(ai_settings.load())}
        self.assertEqual(self.request('/ai-config', 'POST', payload)[0], 403)
        status, _, body = self.request('/ai-config', 'POST', payload, self.auth())
        self.assertEqual(status, 200)
        saved = json.loads(body)
        self.assertEqual(saved['settings']['known_repositories'], ['example/repo'])
        snapshot = json.loads(self.request('/api/state')[2])
        self.assertEqual(snapshot['ai']['settings']['known_repositories'], ['example/repo'])
        self.assertEqual(self.request('/ai-config', 'POST', payload, self.auth())[0], 400)
        payload = {'settings': saved['settings'], 'revision': saved['revision']}
        payload['settings']['known_repositories'] = ['owner/*']
        self.assertEqual(self.request('/ai-config', 'POST', payload, self.auth())[0], 400)
        self.assertEqual(ai_settings.load()['known_repositories'], ['example/repo'])

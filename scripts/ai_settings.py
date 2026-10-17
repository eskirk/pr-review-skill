"""Atomic per-feature AI configuration with lazy migration of existing settings."""
import copy
import hashlib
import json
import re
import pr_review_tracker as tracker
from agent_options import CATALOG, DEFAULTS

KNOWN_REPOSITORIES_LIMIT = 200
REPOSITORY_PATTERN = re.compile(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?/[A-Za-z0-9._-]{1,100}')


def validate_known_repositories(values):
    if not isinstance(values, list) or len(values) > KNOWN_REPOSITORIES_LIMIT:
        raise ValueError('Enter at most 200 repositories, one owner/repo per line.')
    result = []
    for value in values:
        if not isinstance(value, str) or not REPOSITORY_PATTERN.fullmatch(value.strip()):
            raise ValueError('Use owner/repo for each repository (no URLs or wildcards).')
        value = value.strip().lower()
        if value.split('/')[1] in ('.', '..'):
            raise ValueError('Use a valid repository name.')
        if value not in result:
            result.append(value)
    return result


def load():
    import pr_dashboard as dashboard
    raw = tracker.read_json(dashboard.config_path(), required=False)
    if 'ai' in raw:
        result = copy.deepcopy(raw['ai'])
        result.setdefault('known_repositories', [])
        return result
    # Read-only migration. Persist only when settings are explicitly saved.
    result = {key: {'provider': 'codex', 'profiles': copy.deepcopy(profiles)} for key, profiles in DEFAULTS.items()}
    legacy = raw.get('agent_profiles', {})
    provider = raw.get('agent', 'claude')
    if provider not in ('claude', 'codex'):
        provider = 'claude'
    for key in ('codex', 'claude'):
        if key in legacy:
            result['review']['profiles'][key] = {field: str(legacy[key].get(field, '')) for field in ('model', 'effort')}
    if provider not in legacy:
        result['review']['profiles'][provider] = {field: str(raw.get(field, '')) for field in ('model', 'effort')}
    result['review']['provider'] = provider
    # Chat previously always read the Codex profile, including runtime defaults.
    result['chat']['profiles']['codex'] = {field: str(legacy.get('codex', {}).get(field, raw.get(field, '') if provider == 'codex' else '')) for field in ('model', 'effort')}
    old_triage = tracker.read_json(tracker.tracker_root()/'triage.json', required=False).get('config', {})
    provider = old_triage.get('provider', 'codex')
    if provider not in CATALOG:
        provider = 'codex'
    result['triage'].update(provider=provider, enabled=old_triage.get('enabled', False),
                            daily_limit=old_triage.get('daily_limit', 30), batch_limit=old_triage.get('batch_limit', 10))
    result['triage']['profiles'][provider] = {'model': old_triage.get('model', DEFAULTS['triage'][provider]['model']), 'effort': old_triage.get('reasoning', '')}
    result['known_repositories'] = []
    return result


def revision(settings):
    return hashlib.sha256(json.dumps(settings, sort_keys=True).encode()).hexdigest()


def selected(feature, settings=None):
    entry = (settings or load())[feature]
    return {'provider': entry['provider'], **entry['profiles'][entry['provider']]}


def validate_profile(provider, profile):
    if not isinstance(profile, dict) or set(profile) != {'model', 'effort'}:
        raise ValueError('Choose a model and reasoning level.')
    model, effort = profile['model'], profile['effort']
    if not isinstance(model, str) or not isinstance(effort, str) or not re.fullmatch(r'[A-Za-z0-9._:-]{0,160}', model) or not re.fullmatch(r'[a-z]{0,40}', effort):
        raise ValueError('Invalid model or reasoning level.')
    if (provider == 'claude' and model.startswith('gpt-')) or (provider != 'claude' and model.startswith('claude-')):
        raise ValueError('The model belongs to a different provider.')
    allowed = CATALOG[provider]['model_efforts'].get(model, CATALOG[provider]['efforts'])
    if effort not in allowed:
        raise ValueError('Choose a supported reasoning level for this model.')


def save(settings, expected_revision=None):
    import pr_dashboard as dashboard
    with dashboard.state_lock():
        previous = load()
        if expected_revision is not None and expected_revision != revision(previous):
            raise ValueError('AI settings changed in another window. Reload before saving.')
        if not isinstance(settings, dict) or set(settings) != set(DEFAULTS) | {'known_repositories'}:
            raise ValueError('Configure Triage, AI review and Chat.')
        settings = copy.deepcopy(settings)
        settings['known_repositories'] = validate_known_repositories(settings['known_repositories'])
        for feature in DEFAULTS:
            entry = settings[feature]
            if not isinstance(entry, dict) or not isinstance(entry.get('provider'), str) or entry['provider'] not in DEFAULTS[feature]:
                raise ValueError('Choose a supported provider for each feature.')
            if not isinstance(entry.get('profiles'), dict) or set(entry['profiles']) != set(DEFAULTS[feature]):
                raise ValueError('Missing provider profiles.')
            for provider, profile in entry['profiles'].items():
                # Preserve old/custom values; validate every changed profile.
                if profile != previous[feature]['profiles'].get(provider):
                    validate_profile(provider, profile)
        triage = settings['triage']
        if type(triage.get('enabled')) is not bool or type(triage.get('daily_limit')) is not int or not 1 <= triage['daily_limit'] <= 100:
            raise ValueError('Choose automatic estimates and a daily limit from 1 to 100.')
        if type(triage.get('batch_limit')) is not int or not 1 <= triage['batch_limit'] <= 20:
            raise ValueError('Invalid legacy batch limit.')
        raw = dashboard.load_config()
        raw['ai'] = copy.deepcopy(settings)
        # Keep existing CLI consumers compatible with the review profile.
        review = selected('review', settings)
        raw.update(agent=review['provider'], model=review['model'], effort=review['effort'], agent_profiles=settings['review']['profiles'])
        tracker.atomic_write(dashboard.config_path(), raw)
        return {'settings': settings, 'revision': revision(settings)}


def triage_config():
    settings = load()
    entry = settings['triage']
    config = selected('triage', settings)
    return {key: entry[key] for key in ('enabled', 'daily_limit', 'batch_limit')} | {
        'provider': config['provider'], 'model': config['model'], 'reasoning': config['effort']}


def configure_triage(values):
    settings = load()
    previous_revision = revision(settings)
    entry = settings['triage']
    provider = values.get('provider', entry['provider'])
    if provider not in DEFAULTS['triage']:
        raise ValueError('Choose a supported triage provider.')
    entry['provider'] = provider
    entry.update({key: values[key] for key in ('enabled', 'daily_limit', 'batch_limit') if key in values})
    profile = entry['profiles'][provider]
    if 'model' in values: profile['model'] = values['model']
    if 'reasoning' in values: profile['effort'] = values['reasoning']
    save(settings, previous_revision)
    return triage_config()

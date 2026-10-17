"""The advisory verdict follows fixed rules, whatever the model writes around it."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import render_review
import review_verdict
import test_renderer
import test_dashboard as fixtures
import dashboard_runtime as runtime

FULL = {'complete': True, 'traced': True, 'tests': 'pass', 'runtime': 'validated',
        'why': ['Small change.'], 'checked': ['Ran the tests: 12 passed']}


def finding(summary):
    return f'<details class="review-finding">\n<summary>{summary}</summary>\n\nWhy it matters.\n\n</details>\n'


def review(*summaries, **verdict):
    return {'markdown': '\n'.join(finding(s) for s in summaries) or 'No findings.',
            'verdict': {**FULL, **verdict}}


class Rules(unittest.TestCase):
    def test_worst_finding_decides_kind_and_tone(self):
        cases = [((), 'ready', 'good', 'Ready to approve'),
                 (('P3 · Typo', 'Optional · Test'), 'nits', 'good', 'Approvable · 2 small suggestions'),
                 (('Needs confirmation · Dedup?', 'P3 · Typo'), 'question', 'warn', 'Settle one question first'),
                 (('P2 · Retries 4xx', 'Needs confirmation · Dedup?'), 'changes', 'warn', 'Worth fixing first · 1 issue'),
                 (('P1 · Unbounded queue', 'P2 · Retries 4xx'), 'blocked', 'bad', 'Changes needed · 1 serious issue'),
                 (('P0 · Data loss',), 'blocked', 'bad', 'Changes needed · 1 serious issue')]
        for summaries, kind, tone, headline in cases:
            with self.subTest(summaries=summaries):
                result = review_verdict.derive(review(*summaries))
                self.assertEqual((result['kind'], result['tone'], result['headline']), (kind, tone, headline))

    def test_confidence_counts_coverage_gaps(self):
        self.assertEqual(review_verdict.derive(review())['confidence'], 'high')
        self.assertEqual(review_verdict.derive(review(runtime='not-run'))['confidence'], 'medium')
        self.assertEqual(review_verdict.derive(review(tests='not-run', runtime='not-run'))['confidence'], 'medium')
        self.assertEqual(review_verdict.derive(review(tests='fail'))['confidence'], 'low')
        self.assertEqual(review_verdict.derive(review(runtime='not-needed'))['confidence'], 'high')

    def test_green_with_low_confidence_turns_orange(self):
        result = review_verdict.derive(review(traced=False, tests='not-run', runtime='not-run'))
        self.assertEqual((result['kind'], result['tone'], result['confidence']), ('ready', 'warn', 'low'))
        self.assertEqual(result['headline'], 'Probably approvable · check the gaps yourself')
        self.assertEqual(len(result['gaps']), 3)

    def test_incomplete_review_is_grey_without_confidence(self):
        result = review_verdict.derive(review(complete=False, unreviewed=['storage migration']))
        self.assertEqual((result['kind'], result['tone'], result['confidence']), ('partial', 'muted', None))
        self.assertIn('Not reviewed: storage migration.', result['gaps'])

    def test_findings_inside_code_fences_are_ignored(self):
        markdown = '```md\n' + finding('P1 · Example only') + '```\n' + finding('P3 · Real')
        self.assertEqual(review_verdict.findings(markdown), [{'severity': 'P3', 'title': 'Real'}])

    def test_rejects_unknown_severity_and_bad_coverage(self):
        with self.assertRaises(ValueError):
            review_verdict.derive(review('Comment · Unlabelled'))
        for bad in ({'tests': 'maybe'}, {'runtime': ''}, {'why': []}, {'checked': 'ran'}, {'complete': 'yes'}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                review_verdict.derive(review(**bad))

    def test_check_scope_note_validation_and_confidence(self):
        result=review_verdict.derive(review(tests='fail',tests_note='Reviewer probes failed; repository tests passed.'))
        self.assertIn('Checks failed: Reviewer probes failed; repository tests passed.',result['gaps'])
        self.assertNotIn('Tests fail at this revision.',result['gaps'])
        self.assertEqual(review_verdict.derive(review(tests_note='Repository tests and focused probes.'))['confidence'],'high')
        for note in (None,True,[], 'word '*16):
            with self.subTest(note=note),self.assertRaises(ValueError):
                review_verdict.derive(review(tests_note=note))
        review_verdict.derive(review(tests_note='word '*15))

    def test_legacy_review_without_verdict_uses_severity_only(self):
        result = review_verdict.derive({'markdown': finding('P2 · Retries 4xx')})
        self.assertEqual((result['kind'], result['confidence']), ('changes', None))


class Report(unittest.TestCase):
    setUpClass = classmethod(test_renderer.RendererTests.setUpClass.__func__)
    tearDownClass = classmethod(test_renderer.RendererTests.tearDownClass.__func__)

    def verdict_input(self, **verdict):
        d = copy.deepcopy(self.data)
        d['review'].update(review('P3 · The log says retrying', 'Optional · Add a 429 test', **verdict),
                           assessment='Safe to approve with **two** small suggestions.')
        return d

    def test_card_replaces_assessment_box_and_starts_collapsed(self):
        output = render_review.render(self.verdict_input())
        self.assertIn('<details class="verdict tone-good" id="review-assessment"><summary class="verdict-head">', output)
        self.assertNotIn('Current assessment', output)
        self.assertIn('Approvable · 2 small suggestions', output)
        self.assertIn('High confidence', output)
        self.assertIn('<strong>two</strong>', output)
        self.assertIn(f'<code>{self.head[:12]}</code> · 2 things to consider</span>', output)
        self.assertLess(output.index('</summary>'), output.index('Safe to approve'))
        self.assertLess(output.index('id="review-assessment"'), output.index('id="code"'))

    def test_check_scope_note_is_visible_and_escaped(self):
        output=render_review.render(self.verdict_input(tests='fail',tests_note='Only reviewer probes failed.'))
        self.assertIn('Checks failed: Only reviewer probes failed.',output)
        self.assertNotIn('Tests fail at this revision',output)
        output=render_review.render(self.verdict_input(tests_note='<script>Reviewer probes</script>'))
        self.assertIn('Tests passed · &lt;script&gt;Reviewer probes&lt;/script&gt;',output)
        self.assertEqual(output.count('<script>'),1)

    def test_paper_names_coverage_gaps_in_verdict_and_glance(self):
        d=self.verdict_input(runtime='not-run');d['layout']='paper'
        d['glance']={'kind':'logic','blast':'contained','blast_reason':'One counter changes.'}
        for section in d['sections']:section['claim']=section['title']
        output=render_review.render(d)
        self.assertIn('2 findings · 1 coverage gap</span>',output)
        d['review']['markdown']='No findings.'
        output=render_review.render(d)
        self.assertIn('No findings · 1 coverage gap</strong>',output)
        self.assertIn(' · 1 coverage gap</span>',output)
        self.assertNotIn('thing to consider',output)

    def test_consider_links_resolve_to_numbered_findings(self):
        output = render_review.render(self.verdict_input())
        for i in (1, 2):
            self.assertIn(f'href="#finding-{i}" data-open-finding', output)
            self.assertEqual(output.count(f'id="finding-{i}"'), 1)

    def test_verdict_requires_assessment_and_reserves_finding_ids(self):
        d = self.verdict_input(); del d['review']['assessment']
        with self.assertRaises(ValueError): render_review.render(d)
        d = self.verdict_input(); d['sections'][0]['id'] = 'finding-1'
        with self.assertRaises(ValueError): render_review.render(d)

    def test_update_shows_previous_verdict_from_saved_input(self):
        with tempfile.TemporaryDirectory() as root:
            previous = Path(root) / 'old'; previous.mkdir()
            old = copy.deepcopy(self.data)
            old['review'].update(review('P2 · Invalid batches are retried'), assessment='Fix one.')
            (previous / 'input.json').write_text(json.dumps(old))
            d = self.verdict_input()
            d['update'] = {'scope': 'update', 'previous': {'run_id': 'old', 'base': self.base, 'head': 'a' * 40},
                           'summary': 'Fixed the retry.',
                           'findings': [{'title': 'Invalid batches are retried', 'status': 'resolved', 'note': 'Reproduced again.'}]}
            with patch('render_review.tracker.run_dir', return_value=previous), \
                 patch('render_review.update_record', return_value=d['update']):
                output = render_review.render(d)
        self.assertIn('Previous review at <code>aaaaaaaaaaaa</code>: <span class="verdict-chip tone-warn">', output)
        self.assertIn('Worth fixing first · 1 issue</span>. Fixed since: Invalid batches are retried.', output)
        start = output.index('<summary class="verdict-head">')
        summary = output[start:output.index('</summary>', start)]
        self.assertIn('· ✓ 1 earlier issue fixed', summary)
        self.assertNotIn('verdict-chip', summary)

    def test_cli_writes_and_clears_dashboard_sidecar(self):
        with tempfile.TemporaryDirectory() as directory:
            source, output = Path(directory) / 'input.json', Path(directory) / 'review.html'
            sidecar = output.with_name('review-verdict.json')
            def run(data):
                source.write_text(json.dumps(data))
                subprocess.run([sys.executable, str(Path(render_review.__file__)), str(source), str(output)],
                               check=True, capture_output=True)
            run(self.verdict_input(runtime='not-run'))
            value = json.loads(sidecar.read_text())
            self.assertEqual({k: value[k] for k in ('kind', 'tone', 'confidence', 'short', 'head')},
                             {'kind': 'nits', 'tone': 'good', 'confidence': 'medium', 'short': 'Approvable', 'head': self.head})
            run(self.data)
            self.assertFalse(sidecar.exists())


class Dashboard(fixtures.Isolated):
    def test_completed_report_exposes_matching_verdict_only(self):
        run = self.create_run()
        path = self.artifact(run, 'review-html', 'review.html')
        self.complete(run)
        head = runtime.snapshot()['prs'][0]['artifacts']['review-html']['head_sha']
        sidecar = Path(path).with_name('review-verdict.json')
        sidecar.write_text(json.dumps({'kind': 'blocked', 'tone': 'bad', 'headline': 'Changes needed · 1 serious issue',
                                       'confidence': 'high', 'head': head}))
        verdict = runtime.snapshot()['prs'][0]['artifacts']['review-html']['verdict']
        self.assertEqual(verdict, {'short': 'Changes needed', 'tone': 'bad', 'headline': 'Changes needed · 1 serious issue', 'confidence': 'high'})
        for bad in ({'kind': 'great', 'tone': 'bad'}, {'kind': 'blocked', 'tone': 'red'},
                    {'kind': 'ready', 'tone': 'good', 'head': 'f' * 40}):
            with self.subTest(bad=bad):
                sidecar.write_text(json.dumps({'confidence': 'high', 'head': head, **bad}))
                self.assertIsNone(runtime.snapshot()['prs'][0]['artifacts']['review-html']['verdict'])


if __name__ == '__main__':
    unittest.main()

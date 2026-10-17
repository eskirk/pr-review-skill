import copy
from html.parser import HTMLParser
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from render_review import render, attachment_urls, OverviewWords
from unittest.mock import patch

class SourceText(HTMLParser):
    def __init__(self):super().__init__();self.depth=0;self.current='';self.lines=[]
    def handle_starttag(self,tag,attrs):
        if tag=='span':
            if self.depth:self.depth+=1
            elif dict(attrs).get('class')=='source-text':self.depth=1;self.current=''
    def handle_endtag(self,tag):
        if tag=='span' and self.depth:
            self.depth-=1
            if not self.depth:self.lines.append(self.current)
    def handle_data(self,data):
        if self.depth:self.current+=data

class RendererTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.repo=Path(cls.temp.name)
        def git(*args):return subprocess.check_output(['git','-C',str(cls.repo),*args],text=True).strip()
        git('init','--quiet');git('config','commit.gpgsign','false');git('config','core.hooksPath','/dev/null');git('config','user.email','test@example.invalid');git('config','user.name','Fixture')
        cls.before=['class Demo {','  final count = 1;','','  // <script> & "quoted"','}']
        cls.after=['class Demo {','  final count = 2;','','  // <script> & "quoted"','  String name = "åβ";','}']
        (cls.repo/'demo.dart').write_text('\n'.join(cls.before)+'\n');git('add','demo.dart');git('commit','--quiet','-m','base');cls.base=git('rev-parse','HEAD')
        (cls.repo/'demo.dart').write_text('\n'.join(cls.after)+'\n');git('add','demo.dart');git('commit','--quiet','-m','head');cls.head=git('rev-parse','HEAD')
        cls.data=dict(title='A change',outcome='One value changes.',stack='Dart',repository=str(cls.repo),repo_url='https://github.com/example/repo',pr_url='https://github.com/example/repo/pull/1',base=cls.base,head=cls.head,mode='Brief · Small',evidence={'claims':['fixture']},sections=[{'id':'code','title':'How it works','blocks':[{'type':'source','path':'demo.dart','side':'base','start':1,'end':5,'caption':'Old source.'},{'type':'source','path':'demo.dart','start':1,'end':6,'caption':'New source.'}]}])
        cls.data['review']={'base':cls.base,'head':cls.head,'markdown':'No actionable defects found. Source reviewed; runtime not exercised.'}
    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()
    def test_exact_lines_and_markers(self):
        output=render(self.data);p=SourceText();p.feed(output)
        self.assertEqual(p.lines,self.before+self.after)
        self.assertIn('class="code-line removed" data-line="2"',output)
        self.assertIn('class="code-line added" data-line="2"',output)
        self.assertIn('class="code-line context" data-line="3"',output)
        self.assertIn('/blob/'+self.base+'/demo.dart#L1-L5',output)
    def test_untrusted_text_is_inert(self):
        d=copy.deepcopy(self.data);d['title']='</title><script>alert(1)</script>';d['sections'].append({'id':'example','title':'Example','blocks':[{'type':'example','language':'text','code':'</code></pre><img src=x onerror=alert(1)>','caption':'Authored example.'}]})
        output=render(d);self.assertEqual(output.count('<script>'),1);self.assertNotIn('<img src=x',output);self.assertIn('Illustrative text',output)
    def test_reject_unsafe_links_and_paths(self):
        for value in ('javascript:alert(1)','https://user:password@example.com','file:///tmp/file'):
            d=copy.deepcopy(self.data);d['references']=[{'label':'bad','url':value}]
            with self.assertRaises(ValueError):render(d)
        d=copy.deepcopy(self.data);d['sections'][0]['blocks'][0]['path']='../secret'
        with self.assertRaises(ValueError):render(d)
    def test_quiz_mapping_varies_and_retains_correct_text(self):
        d=copy.deepcopy(self.data);d['questions']=[{'question':'Which?','options':['yes','no','maybe'],'answer':0,'explanation':'Because source.'} for _ in range(3)]
        output=render(d)
        for i in range(3):self.assertIn(f'data-answer="{i}"',output)
        self.assertIn('C. yes',output)
        self.assertIn('quiz-explanation" hidden',output)
    def test_working_tree_no_false_permalink(self):
        d=copy.deepcopy(self.data);d['head']='working-tree';d['review']['head']='working-tree';d['sections'][0]['blocks']=d['sections'][0]['blocks'][1:]
        output=render(d);self.assertNotIn('/blob/',output);self.assertNotIn('/files#',output)
    def test_review_link_restricts_local_artifacts(self):
        with patch('render_review.tracker.tracker_root', return_value=self.repo/'.local/share/pr-review-tracker'):
            notes=self.repo/'.local/share/pr-review-tracker/runs/demo/review.md'
            notes.parent.mkdir(parents=True,exist_ok=True);notes.write_text('Review')
            self.assertIn(notes.resolve().as_uri(),str(attachment_urls({'attachments':[str(notes)]})))
            outside=self.repo/'other.md';outside.write_text('Other')
            with self.assertRaises(ValueError):attachment_urls({'attachments':[str(outside)]})
    def test_reject_mixed_revision_or_missing_findings(self):
        d=copy.deepcopy(self.data);d['review']['head']='f'*40
        with self.assertRaises(ValueError):render(d)
        d=copy.deepcopy(self.data);del d['review']
        with self.assertRaises(ValueError):render(d)
    def test_embeds_findings_after_explanation_and_escapes_drafts(self):
        d=copy.deepcopy(self.data)
        d['review']['markdown']='### A defect\n\n<!-- review-comment:start -->\nCould this preserve `<script>`?\n\n```py\na < b\n```\n<!-- review-comment:end -->'
        d['verification']='Read the source; no runtime check.'
        output=render(d)
        self.assertLess(output.index('id="code"'),output.index('id="review-findings"'))
        self.assertIn('class="copy-comment"',output)
        self.assertIn('a &lt; b',output)
        self.assertIn('id="verification"',output)
        self.assertEqual(output.count('<script>'),1)
    def test_attribution_footer_ends_every_draft_and_its_copy(self):
        d=copy.deepcopy(self.data)
        d['review']['markdown']='<details class="review-finding">\n<summary>P2 · Retry is skipped</summary>\n\n<!-- review-comment:start -->\nCould we retry?\n<!-- review-comment:end -->\n\n</details>'
        d['comment_attribution']={'tool':'Codex','model':'gpt-6.1-sol','person':'Robert'}
        output=render(d)
        self.assertIn("Could we retry?\n\n*Posted by Codex (gpt-6.1-sol) on Robert&#x27;s behalf.*</textarea>",output)
        self.assertIn("<em>Posted by Codex (gpt-6.1-sol) on Robert&#x27;s behalf.</em>",output)
        d['comment_attribution']={'tool':'Claude Code','person':'Robert'}
        self.assertIn("*Posted by Claude Code on Robert&#x27;s behalf.*</textarea>",render(d))
        for bad in [{'tool':'Codex'},{'tool':'Codex','person':'R_b'},{'tool':'Codex','person':'Robert','extra':'x'},'Codex']:
            d['comment_attribution']=bad
            with self.assertRaises(ValueError):render(d)
    def test_ranges_fail_instead_of_inventing_code(self):
        for start,end in [(0,2),(2,99),(3,2)]:
            d=copy.deepcopy(self.data);d['sections'][0]['blocks'][0].update(start=start,end=end)
            with self.assertRaises(ValueError):render(d)

    def test_assessment_is_visible_once_before_walkthrough_with_drafts_still_in_findings(self):
        d=copy.deepcopy(self.data)
        d['review']['assessment']='Request changes: **one contract defect**. Runtime not exercised.'
        d['review']['markdown']='<!-- review-comment:start -->\nCould we retain the valid items?\n<!-- review-comment:end -->'
        output=render(d)
        self.assertLess(output.index('id="review-assessment"'),output.index('id="code"'))
        self.assertLess(output.index('id="review-findings"'),output.index('class="review-comment"'))
        self.assertEqual(output.count('Request changes:'),1)
        self.assertIn('<strong>one contract defect</strong>',output)
        self.assertIn('href="#review-findings">Jump to findings and checks',output)

    def test_assessment_rejects_hidden_verdicts_drafts_and_unsafe_links(self):
        for assessment in ['', None, '<details>\n<summary>Verdict</summary>\nHidden verdict\n</details>',
                           '<!-- review-comment:start -->\nDraft\n<!-- review-comment:end -->',
                           '> <details>\n> <summary>Hidden verdict</summary>\n> Do not merge\n> </details>',
                           '> <!-- review-comment:start -->\n> Draft\n> <!-- review-comment:end -->',
                           '[Bad](https://user:password@example.com)']:
            d=copy.deepcopy(self.data);d['review']['assessment']=assessment
            with self.assertRaises(ValueError):render(d)
        d=copy.deepcopy(self.data);d['review']['assessment']='<script>alert(1)</script>'
        output=render(d)
        self.assertEqual(output.count('<script>'),1)
        self.assertIn('&lt;script&gt;',output)

    def test_legacy_input_still_has_one_visible_assessment_in_findings(self):
        output=render(self.data)
        self.assertNotIn('id="review-assessment"',output)
        self.assertEqual(output.count('No actionable defects found.'),1)

    def test_reading_estimate_excludes_nested_optional_evidence_and_code(self):
        self.assertEqual(OverviewWords().count('<p>Visible &amp; relevant.</p><details><summary>Optional</summary><p>Hidden</p><details><summary>More</summary>Hidden too</details></details><pre>code code</pre><p>Still visible.</p>'),5)
        d=copy.deepcopy(self.data)
        before=render(d)
        d['verification']='Lengthy evidence. '*1000
        d['review']['markdown']='Lengthy legacy finding. '*1000
        after=render(d)
        import re
        estimate=r'approximately (\d+) min overview'
        self.assertEqual(re.search(estimate,before)[1],re.search(estimate,after)[1])

    def test_diagrams_escape_authored_labels_and_keep_all_scenario_states_without_js(self):
        d=copy.deepcopy(self.data)
        flow={'type':'flow','title':'A batch','caption':'Illustration','steps':[{'icon':'storage','label':'<script>bad</script>','detail':'On disk','state':'active'}]}
        d['sections'].append({'id':'flush','title':'Flushing','blocks':[{'type':'scenario','title':'Trace a batch','caption':'Source-traced','frames':[{'label':'Pending','blocks':[flow]},{'label':'Flushed','blocks':[{'type':'paragraph','text':'Export attempted'}]}]}]})
        output=render(d)
        self.assertIn('&lt;script&gt;bad&lt;/script&gt;',output)
        self.assertEqual(output.count('<script>'),1)
        self.assertIn('class="scenario-controls" hidden',output)
        self.assertNotIn('class="scenario-frame" hidden',output)
        self.assertIn('Export attempted',output)
        self.assertIn('<h4 class="scenario-frame-label">Pending</h4>',output)
        self.assertIn('<h4 class="scenario-frame-label">Flushed</h4>',output)
        d['review']['visuals']={'status':d['sections'][-1]['blocks'][0]}
        d['review']['assessment']='<!-- review-visual:status -->'
        with self.assertRaises(ValueError):render(d)

    def test_finding_visual_renders_outside_copy_and_fenced_markers_stay_literal(self):
        d=copy.deepcopy(self.data)
        d['review']['visuals']={'timeout':{'type':'sequence','title':'Timeout path','caption':'Source trace','steps':[{'from':'Caller','to':'Exporter','message':'Argument omitted','state':'blocked'}]}}
        d['review']['markdown']='<!-- review-visual:timeout -->\n\n<!-- review-comment:start -->\nCould we forward the timeout?\n<!-- review-comment:end -->\n\n```text\n<!-- review-visual:timeout -->\n```'
        output=render(d)
        self.assertEqual(output.count('<figure class="sequence">'),1)
        self.assertLess(output.index('<figure class="sequence">'),output.index('class="review-comment"'))
        self.assertIn('&lt;!-- review-visual:timeout --&gt;',output)
        d['review']['markdown']='<!-- review-comment:start -->\n<!-- review-visual:timeout -->\n<!-- review-comment:end -->'
        with self.assertRaises(ValueError):render(d)
        d['review']['markdown']='<!-- review-visual:missing -->'
        with self.assertRaises(ValueError):render(d)
    def test_authored_diagram_is_allowlisted_and_rendered_inert(self):
        d=copy.deepcopy(self.data)
        markup='<div class="dg-stack"><div class="dg-node dg-bad">Throws &lt;error&gt; <span class="dg-badge">⚠ Finding 1</span></div><div class="dg-arrow"></div><svg viewBox="0 0 10 10" role="img" aria-label="Arrow"><defs><marker id="dg-head"><path d="M0 0L5 5"/></marker></defs><line x1="0" y1="0" x2="5" y2="5" marker-end="url(#dg-head)"/><text x="1" y="9">A &amp; B</text></svg></div>'
        d['sections'].append({'id':'shape','title':'Shape','blocks':[{'type':'diagram','title':'Decision','html':markup,'caption':'Source-traced.'}]})
        output=render(d)
        self.assertIn('<figure class="diagram">',output);self.assertIn('Throws &lt;error&gt;',output);self.assertIn('marker-end="url(#dg-head)"',output)
        self.assertIn('viewbox="0 0 10 10"',output);self.assertIn('A &amp; B',output)
        for bad in ('<script>alert(1)</script>','<div onclick="x">a</div>','<a href="https://example.com">x</a>','<img src="data:image/png;base64,AA">',
                    '<div style="background:url(https://example.com/x)">x</div>','<div class="review-comment">x</div>','<div id="review-findings">x</div>',
                    '<style>.x{}</style>','<svg><use href="#dg-a"/></svg>','<svg><foreignObject>x</foreignObject></svg>','<div>unclosed','<b><i>x</b></i>',
                    '<div style="color:re\\64">x</div>','<div data-x="1">x</div>'):
            with self.subTest(bad=bad):
                d['sections'][-1]['blocks'][0]['html']=bad
                with self.assertRaises(ValueError):render(d)
    def test_cases_grid_marks_outcomes_in_words_and_links_findings(self):
        d=copy.deepcopy(self.data)
        grid={'type':'cases','title':'What happens in each situation','columns':['Situation','Before','After'],'caption':'Source-traced.',
              'rows':[{'situation':'Normal test','cells':[{'status':'works','text':'test driver'},{'status':'works','text':'test driver'}]},
                      {'situation':'Custom <binding>','finding':'Finding 1','cells':[{'status':'works','text':'test driver'},{'status':'breaks','text':'real driver'}]}]}
        d['sections'].append({'id':'cases','title':'Cases','blocks':[grid]})
        output=render(d)
        self.assertIn('<figure class="cases">',output);self.assertIn('Custom &lt;binding&gt;',output);self.assertIn('⚠ Finding 1',output)
        self.assertIn('<span class="visually-hidden">Breaks: </span>real driver',output)
        for broken in ({'columns':['Only']},{'rows':[]},{'rows':[{'situation':'x','cells':[{'status':'works','text':'a'}]}]},{'rows':[{'situation':'x','cells':[{'status':'great','text':'a'},{'text':'b'}]}]}):
            with self.subTest(broken=broken):
                d['sections'][-1]['blocks'][0]={**grid,**broken}
                with self.assertRaises(ValueError):render(d)
    def test_finding_visuals_accept_diagrams_and_cases(self):
        d=copy.deepcopy(self.data)
        d['review']['visuals']={'path':{'type':'diagram','html':'<div class="dg-node dg-bad">Retry skipped</div>','caption':'Where it fails.'}}
        d['review']['markdown']='<details class="review-finding">\n<summary>P2 · Retry is skipped</summary>\n\n<!-- review-visual:path -->\n\n<!-- review-comment:start -->\nCould we retry?\n<!-- review-comment:end -->\n\n</details>'
        output=render(d)
        self.assertLess(output.index('Retry skipped'),output.index('Could we retry?'))
        d['review']['assessment']='<!-- review-visual:path -->'
        with self.assertRaises(ValueError):render(d)
    def test_flow_without_icon_shows_step_number(self):
        d=copy.deepcopy(self.data)
        d['sections'].append({'id':'flow','title':'Flow','blocks':[{'type':'flow','title':'Check','caption':'Trace.','steps':[{'label':'A','detail':'first'},{'label':'B','detail':'second','icon':'app'}]}]})
        output=render(d)
        self.assertIn('<span class="flow-number" aria-hidden="true">1</span>',output);self.assertNotIn('flow-number" aria-hidden="true">2',output)

if __name__=='__main__':unittest.main()


SEQUENCE_SVG = ('<svg id="{id}" width="100%" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><style>#x{{fill:red}}</style>'
                '<defs><symbol id="{id}-computer"><path d="M0 0"/></symbol></defs>'
                '<g data-et="participant" data-id="A"><rect class="actor"/><text class="actor">App</text></g>'
                '<line class="messageLine0" data-et="message" data-from="A" data-to="B" marker-end="url(#{id}-arrowhead)" onclick="x()"/></svg>')

class WalkReportTests(unittest.TestCase):
    """The walk layout, its blocks and pre-rendered Mermaid (runtime stubbed)."""
    @classmethod
    def setUpClass(cls):
        RendererTests.setUpClass();cls.base_data=RendererTests.data;cls.cleanup=RendererTests.temp
    @classmethod
    def tearDownClass(cls):cls.cleanup.cleanup()
    def walk(self,**extra):
        d=copy.deepcopy(self.base_data);d['layout']='walk';d['stats']={'additions':12,'deletions':3,'files':1}
        source='sequenceDiagram\n  A->>B: hi'
        d['sections']=[{'id':'what','tab':'What changed','title':'What changed','claim':'One claim.','lede':'In plain words.','blocks':[
            {'type':'compare','stacked':True,'panes':[{'label':'Before','tone':'before','blocks':[{'type':'mermaid','source':source,'notes':{'App':'Starts it.'}}]},
                                                     {'label':'After','tone':'after','blocks':[{'type':'paragraph','text':'Now.'}]}]},
            {'type':'callouts','items':[{'tone':'bad','title':'Breaks.','text':'Both wait.','finding':'Finding 1'}]}]},
            {'id':'how','title':'How it works','blocks':[{'type':'pair','change':'The value changes.','blocks':[{'type':'card','icon':'lock','name':'Demo','role':'Holds <count>.','tag':'changed','tone':'hot'}],
             'diff':[{'type':'source','path':'demo.dart','start':1,'end':3,'caption':'Here.'}]}]}]
        d.update(extra);return d
    def render(self,d):
        import review_mermaid
        def runtime(items):return {item['id']:{'svg':SEQUENCE_SVG.format(id=item['id'])} for item in items}
        with patch.object(review_mermaid,'cache_dir',return_value=None),patch.object(review_mermaid,'run_runtime',side_effect=runtime) as call:
            return render(d),call
    def test_walk_layout_renders_scenes_blocks_and_fonts(self):
        output,call=self.render(self.walk())
        self.assertEqual(call.call_count,1)
        self.assertIn('data-layout="walk"',output);self.assertIn('<nav class="walk-rail"',output)
        self.assertIn('<a href="#what">What changed</a>',output);self.assertIn('<h2>One claim.</h2>',output)
        self.assertIn('+12</span>',output);self.assertIn("font-src data:",output);self.assertIn('@font-face{font-family:"Fraunces"',output)
        self.assertIn('walk-pane tone-before',output);self.assertIn('walk-callout tone-bad',output);self.assertIn('⚠ Finding 1',output)
        self.assertIn('walk-card tag-changed tone-hot',output);self.assertIn('Holds &lt;count&gt;.',output)
        self.assertIn('<div data-participant="App">Starts it.</div>',output)
        # Mermaid's own style, icon symbols and event handlers never reach the page.
        self.assertNotIn('fill:red',output);self.assertNotIn('-computer',output);self.assertNotIn('onclick',output)
        self.assertIn('data-from="A"',output)
    def test_classic_layout_is_unchanged_by_default(self):
        output=render(copy.deepcopy(self.base_data))
        self.assertIn('data-layout="classic"',output);self.assertIn('font-src &#x27;none&#x27;',output);self.assertNotIn('@font-face',output)
        self.assertIn('<nav aria-label="On this page">',output)
    def test_walk_places_the_update_record_after_the_findings(self):
        d=self.walk(update={'scope':'full','previous':{'run_id':'','base':self.base_data['base'],'head':self.base_data['head']},'summary':'Fresh full review.'})
        output,_=self.render(d)
        self.assertLess(output.index('id="review-findings"'),output.index('id="since-last-review"'))
        classic=render({**copy.deepcopy(self.base_data),'update':d['update']})
        self.assertLess(classic.index('id="since-last-review"'),classic.index('id="review-findings"'))
    def test_invalid_walk_input_is_rejected(self):
        bad=[self.walk(layout='slides')]
        d=self.walk();d['sections'][0]['blocks'][1]['items'][0]['tone']='purple';bad.append(d)
        d=self.walk();d['sections'][1]['blocks'][0]['blocks'][0]['icon']='rocket';bad.append(d)
        d=self.walk();d['sections'][1]['blocks'][0]['diff']=[{'type':'mermaid','source':'graph TD\n A-->B'}];bad.append(d)
        d=self.walk();d['sections'][0]['blocks'][0]['panes'][0]['blocks'][0]['source']='pie\n "a": 1';bad.append(d)
        for d in bad:
            with self.assertRaises(ValueError):self.render(d)
    def test_mermaid_syntax_errors_name_the_diagram(self):
        import review_mermaid
        with patch.object(review_mermaid,'cache_dir',return_value=None),patch.object(review_mermaid,'run_runtime',side_effect=lambda items:{i['id']:{'error':'page.evaluate: Parse error on line 2'} for i in items}):
            with self.assertRaisesRegex(ValueError,'Mermaid syntax error in the diagram starting “sequenceDiagram”: Parse error on line 2'):render(self.walk())

class MermaidSanitizerTests(unittest.TestCase):
    def test_wrapped_label_rows_keep_a_word_space(self):
        from review_mermaid import spaced_rows
        row='<tspan class="text-outer-tspan row"><tspan class="text-inner-tspan">{}</tspan></tspan>'
        svg=spaced_rows('<text>'+row.format('a fresh')+row.format('emulator')+'</text>')
        self.assertIn('a fresh </tspan></tspan><tspan class="text-outer-tspan',svg)
        self.assertEqual(svg,spaced_rows(svg))

    def test_generated_svg_keeps_hooks_but_drops_active_content(self):
        from review_diagram import sanitize_mermaid, DiagramError
        clean=sanitize_mermaid(SEQUENCE_SVG.format(id='mm-1'))
        self.assertIn('marker-end="url(#mm-1-arrowhead)"',clean);self.assertNotIn('onclick',clean);self.assertNotIn('<style',clean)
        for svg in ('<svg><foreignObject><div>x</div></foreignObject></svg>','<svg><a href="https://x"><text>x</text></a></svg>',
                    '<svg><script>alert(1)</script></svg>','<svg><rect style="fill:url(https://evil/x)"/></svg>'):
            with self.assertRaises(DiagramError):sanitize_mermaid(svg)

class PaperReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        RendererTests.setUpClass();cls.base_data=RendererTests.data;cls.cleanup=RendererTests.temp
    @classmethod
    def tearDownClass(cls):cls.cleanup.cleanup()
    def paper(self):
        d=copy.deepcopy(self.base_data)
        d.update(layout='paper',glance={'kind':'logic','blast':'contained','blast_reason':'One local value changes.'},
                 background={'story':'The counter used a fixed value.','terms':[{'term':'Counter','meaning':'The stored total.'}]})
        d['sections'][0].update(claim='The counter increases',lede='A small adjustment.')
        return d
    def stepper(self):
        return {'type':'stepper','title':'Follow the change','caption':'Source-traced order.',
                'visual':{'type':'sequence','title':'Call order','caption':'Two calls.', 'steps':[
                    {'from':'App','to':'Counter','message':'Read the value.'},
                    {'from':'Counter','to':'App','message':'Return the value.'}]},
                'steps':[{'label':'Read','text':'The app reads the counter.','focus':[1]},
                         {'label':'Return','text':'The counter returns its value.','focus':[2]}]}
    def test_paper_layers_and_collapsed_tail(self):
        d=self.paper();d['verification']='Verified source.';d['references']=[{'label':'Contract','url':'https://example.com/spec'}]
        output=render(d)
        positions=[output.index(x) for x in ('<h1>A change</h1>','<p class="outcome">','<h2>At a glance</h2>','<h2>Before you read</h2>','<h2>The counter increases</h2>','<section id="review-findings"','<details class="paper-tail">')]
        self.assertEqual(positions,sorted(positions))
        self.assertIn('<strong>No findings</strong>',output)
        self.assertIn('<dt>Counter</dt><dd>The stored total.</dd>',output)
        self.assertNotIn('<nav class="walk-rail"',output)
        self.assertNotIn('<div class="walk-scenes"',output)
        self.assertIn("font-src data:",output)
        tail=output[output.index('<details class="paper-tail">'):]
        self.assertIn('id="verification"',tail);self.assertIn('id="references"',tail);self.assertIn('id="provenance"',tail)
    def test_glance_derives_problems_and_can_override_them(self):
        d=self.paper()
        d['review']['markdown']='<details class="review-finding">\n<summary>P2 · The count is wrong</summary>\n\n**The problem in one sentence:** The total drops a value.\n\n</details>\n\n<details class="review-finding">\n<summary>P3 · A label is missing</summary>\n\nA separate explanation.\n\n</details>'
        output=render(d)
        self.assertIn('href="#finding-1" data-open-finding>The total drops a value.</a>',output)
        self.assertIn('href="#finding-2" data-open-finding>A label is missing</a>',output)
        d['glance']['findings']=[{'text':'A clearer description.','finding':'finding-2'}]
        self.assertIn('href="#finding-2" data-open-finding>A clearer description.</a>',render(d))
        for value in (None,{},[{'text':'Bad link.','finding':'Finding 9'}],[{'text':[],'finding':'Finding 1'}],[{'text':'Text','finding':True}]):
            d['glance']['findings']=value
            with self.subTest(value=value),self.assertRaises(ValueError):render(d)
    def test_new_paper_field_validation(self):
        for field,values in {
            'title':[None,'word '*13], 'outcome':[None,''],
            'glance':[None,[],{}, {'kind':'bad','blast':'wide','blast_reason':'Oops'},
                      {'kind':[],'blast':'wide','blast_reason':'Oops'},
                      {'kind':'logic','kind_label':42,'blast':'wide','blast_reason':'Oops'},
                      {'kind':'logic','blast':'huge','blast_reason':'Oops'},
                      {'kind':'logic','blast':'wide','blast_reason':'word '*13}],
            'background':[None,{}, {'story':'Old behavior.','terms':[]},
                          {'story':'Old behavior.','terms':[{'term':'Term','meaning':'word '*100}]},
                          {'story':'Old behavior.','terms':[{'term':'Term','meaning':True}]},
                          {'story':'A. B. C. D.','terms':[{'term':'Term','meaning':'Meaning.'}]},
                          {'story':'Old behavior.','terms':[{'term':'Term','meaning':'Meaning.'}]*6}]
        }.items():
            for value in values:
                d=self.paper();d[field]=value
                with self.subTest(field=field,value=value),self.assertRaises(ValueError):render(d)
        d=self.paper();del d['sections'][0]['claim']
        with self.assertRaises(ValueError):render(d)

    def round_three(self):
        d=self.paper();d.pop('background')
        d['why']={'text':'Readers lost the old value.','sources':[{'label':'Issue #223','url':'https://example.com/223'}],'inferred':False}
        d['orientation']={'open':False,'teaser':'Where the counter sits','map':[
            {'label':'Caller','name':'read','changed':False},{'label':'Counter','name':'Demo','changed':True},{'label':'Result','changed':False}],
            'story':'The caller reads a stored total.','compare':'Like a register, except the value is fixed.','terms':[]}
        d['glance']['judgment']=[{'text':'Should callers see the larger value?','section':'code'}]
        d['sections'][0]['approach']={'text':'Why not just compute the value?','suggested':True}
        return d

    def test_optional_paper_blocks_and_order(self):
        d=self.round_three();output=render(d)
        self.assertLess(output.index('<h1>A change</h1>'),output.index('<h2>Why this PR exists</h2>'))
        self.assertLess(output.index('<h2>Why this PR exists</h2>'),output.index('<p class="outcome">'))
        self.assertIn('<span class="paper-source-chip"><a href="https://example.com/223"',output)
        self.assertIn('<details class="paper-orientation paper-background"><summary>',output)
        self.assertIn('aria-label="You are here"',output);self.assertIn('>this PR</small>',output)
        self.assertIn('<h3>Needs your judgment</h3>',output)
        self.assertIn('href="#code">Should callers see the larger value?',output)
        self.assertIn('our note, not stated by the author',output)
        d['orientation']['open']=True;d['why'].update(sources=[],inferred=True)
        d['sections'][0]['approach']={'text':'The fixed value avoids a query.','source':{'label':'PR description'}}
        output=render(d)
        self.assertIn('paper-background" open>',output);self.assertIn('inferred from the diff</span>',output)
        self.assertIn('>PR description</span>',output)

    def test_round_three_validates_limits_and_links(self):
        for field,values in {
            'why':[None,{'text':'One. Two. Three.','inferred':True},{'text':'word '*46,'inferred':True},
                   {'text':'Reason.','inferred':False,'sources':[]},{'text':'Reason.','inferred':1},
                   {'text':'Reason.','inferred':False,'sources':[{'label':'Bad','url':'http://example.com'}]}],
            'orientation':[None,{'open':False,'teaser':'Where'}, {'open':1,'teaser':'Where','story':'Before.'},
                           {'open':False,'teaser':'word '*13,'story':'Before.'},
                           {'open':False,'teaser':'Where','story':'One. Two. Three. Four.'},
                           {'open':False,'teaser':'Where','story':'word '*120},
                           {'open':False,'teaser':'Where','map':[{'label':'Node','changed':False}]*3},
                           {'open':False,'teaser':'Where','story':'Before.','terms':[{'term':'a','meaning':'b'}]*5}]
        }.items():
            for value in values:
                d=self.round_three();d[field]=value
                with self.subTest(field=field,value=value),self.assertRaises(ValueError):render(d)
        d=self.round_three();d['background']=self.paper()['background']
        with self.assertRaisesRegex(ValueError,'orientation or background'):render(d)
        for value in ([{'text':'One. Two.'}],[{'text':'Question?','section':'missing'}],[{'text':'Question?'}]*4):
            d=self.round_three();d['glance']['judgment']=value
            with self.subTest(value=value),self.assertRaises(ValueError):render(d)
        for value in ({'text':'Note.'},{'text':'One. Two. Three.','suggested':True},
                      {'text':'Note.','source':{'label':'X'},'suggested':True}):
            d=self.round_three();d['sections'][0]['approach']=value
            with self.subTest(value=value),self.assertRaises(ValueError):render(d)
        d=self.round_three();d['glance']['judgment']=[]
        self.assertNotIn('<h3>Needs your judgment</h3>',render(d))

    def test_findings_preview_stops_at_two(self):
        d=self.paper();d['review']['markdown']='\n\n'.join(
            f'<details class="review-finding">\n<summary>P2 · Problem {i}</summary>\n\n**The problem in one sentence:** Value {i} is lost.\n\n</details>' for i in range(1,5))
        output=render(d);glance=output.split('<section class="paper-glance"',1)[1].split('</section>',1)[0]
        self.assertIn('4 findings',glance);self.assertIn('Value 2 is lost.',glance)
        self.assertNotIn('Value 3 is lost.',glance);self.assertIn('>+2 more</a>',glance)

    def test_explicit_open_excerpts_form_a_pair(self):
        d=self.paper();excerpts=copy.deepcopy(d['sections'][0]['blocks'])
        excerpts=[b for b in excerpts if b['type']=='source']
        for b in excerpts:b['open']=True
        walk={'type':'code_walk','items':[{'path':'demo.dart','tag':'changed','text':'The counter changes.','diff':excerpts},
                                         {'path':'caller.dart','tag':'new','text':'The caller reads it.','diff':[{'type':'example','code':'read()','caption':'Read the changed counter.'}]}]}
        d['sections'][0]['blocks']=[walk];output=render(d)
        self.assertIn('<div class="paper-excerpt-pair"><figure',output);self.assertNotIn('<summary>More excerpts</summary>',output)
        excerpts[0]['open']=False;output=render(d)
        self.assertNotIn('<div class="paper-excerpt-pair">',output);self.assertIn('<summary>More excerpts</summary>',output)
        excerpts[1]['open']=False
        with self.assertRaisesRegex(ValueError,'at least one open'):render(d)

    def test_code_walk_badge_comes_from_git(self):
        d=self.paper();source=[b for b in d['sections'][0]['blocks'] if b['type']=='source'][0]
        walk={'type':'code_walk','items':[{'path':'demo.dart','tag':'new','text':'The counter changes.','diff':[source]},
                                         {'path':'caller.dart','tag':'changed','text':'The caller reads it.','diff':[{'type':'example','code':'read()','caption':'Read the changed counter.'}]}]}
        d['sections'][0]['blocks']=[walk];output=render(d)
        self.assertIn('<code>demo.dart</code> <span class="code-walk-tag">changed</span>',output)
        self.assertIn('<code>caller.dart</code> <span class="code-walk-tag">unchanged</span>',output)

    def test_blobless_clone_missing_excerpt_has_clear_error(self):
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run(['git','clone','--quiet','--no-hardlinks',str(RendererTests.repo),directory],check=True)
            subprocess.run(['git','-C',directory,'config','remote.origin.partialclonefilter','blob:none'],check=True)
            d=self.paper();d['repository']=directory
            render(d)  # Full object data in a partial clone remains usable.
            oid=subprocess.check_output(['git','-C',directory,'rev-parse',f'{d["head"]}:demo.dart'],text=True).strip()
            (Path(directory)/'.git'/'objects'/oid[:2]/oid[2:]).unlink()
            with self.assertRaisesRegex(ValueError,'repository is a blobless partial clone; point at a full or --shared clone'):render(d)

    def test_optional_blocks_do_not_change_legacy_output(self):
        for layout in ('classic','walk'):
            d=self.paper();d['layout']=layout;before=render(d)
            optional=self.round_three()
            d.update(why=optional['why'],orientation=optional['orientation'])
            d['glance']['judgment']=optional['glance']['judgment']
            d['sections'][0]['approach']=optional['sections'][0]['approach']
            self.assertEqual(before,render(d))
            self.assertNotIn('// Paper responsive diagrams',before)
    def test_code_walk_exact_excerpts_and_no_nested_disclosures(self):
        d=self.paper()
        walk={'type':'code_walk','example':'Take a counter with one item.','items':[
            {'path':'demo.dart','tag':'changed','text':'The counter increases.','diff':[d['sections'][0]['blocks'][1]]},
            {'path':'caller.dart','tag':'new','text':'The caller reads the counter.','diff':[{'type':'example','code':'read();','caption':'Illustrative caller.'}]}]}
        d['sections'][0]['blocks']=[walk]
        output=render(d);parsed=SourceText();parsed.feed(output)
        self.assertEqual(parsed.lines,RendererTests.after)
        self.assertIn('<div class="code-walk"><p>Take a counter with one item.</p><ol>',output)
        self.assertNotIn('Exact excerpts',output)
        self.assertIn('</p><figure class="source"',output)
        self.assertNotIn('<span class="path">demo.dart</span>',output)
        for change in ({'items':[]},{'items':walk['items']*4}):
            d['sections'][0]['blocks']=[{**walk,**change}]
            with self.assertRaises(ValueError):render(d)
        for change in ({'tag':'existing'},{'tag':[]},{'path':'../secret'},{'text':None},{'text':'One. Two.'},{'text':'one. two.'},{'diff':[]},
                       {'diff':[{'type':'details','title':'Nested','blocks':[]}]},{'diff':[{'type':'paragraph','text':'No excerpt'}]}):
            d['sections'][0]['blocks']=[{**walk,'items':[{**walk['items'][0],**change},walk['items'][1]]}]
            with self.subTest(change=change),self.assertRaises(ValueError):render(d)
    def test_code_walk_first_source_inline_and_paths_once(self):
        d=self.paper();source=d['sections'][0]['blocks'][1]
        example={'type':'example','code':'read();','caption':'Illustrative caller.'}
        d['sections'][0]['blocks']=[{'type':'code_walk','items':[
            {'path':'demo.dart','tag':'changed','text':'The counter increases.','diff':[example,source,source]},
            {'path':'demo.dart','tag':'changed','text':'The counter returns.','diff':[source]}]}]
        output=render(d);body=output.split('<div class="code-walk">',1)[1].split('</ol>',1)[0]
        self.assertEqual(body.count('<code>demo.dart</code>'),2)
        self.assertNotIn('<span class="path">demo.dart</span>',body)
        self.assertLess(body.index('<figure class="source"'),body.index('<details>'))
        self.assertIn('<summary>More excerpts</summary><figure class="source"',body)

    def test_stepper_validation_and_readable_fallback_in_all_layouts(self):
        for layout in ('classic','walk','paper'):
            d=self.paper();d['layout']=layout;d['sections'][0]['blocks']=[self.stepper()]
            output=render(d)
            self.assertNotIn('class="stepper-controls"',output)
            self.assertIn('<li data-focus="[1]"><button type="button" class="stepper-note" aria-pressed="false"><strong>Read</strong><span>The app reads the counter.</span></button></li>',output)
            self.assertIn('The counter returns its value.',output)
            self.assertIn('class="sequence-step normal"',output)
        for change in ({'title':[]},{'caption':None},{'visual':{'type':'diagram'}},{'steps':[]},{'steps':[self.stepper()['steps'][0]]*9}):
            d=self.paper();d['sections'][0]['blocks']=[{**self.stepper(),**change}]
            with self.subTest(change=change),self.assertRaises(ValueError):render(d)
        for change in ({'label':None},{'text':'One. Two.'},{'text':'one. two.'},{'focus':[]},{'focus':[0]},{'focus':[3]},{'focus':[True]},
                       {'focus':[1,1]},{'focus':'1'},{'finding':'Finding 1'}):
            d=self.paper();stepper=self.stepper();stepper['steps'][0].update(change);d['sections'][0]['blocks']=[stepper]
            with self.subTest(change=change),self.assertRaises(ValueError):render(d)
    def test_stepper_defaults_and_graphic_focus_validation(self):
        d=self.paper();stepper=self.stepper()
        for step in stepper['steps']: del step['focus']
        d['sections'][0]['blocks']=[stepper]
        output=render(d)
        self.assertIn('data-focus="[1]"',output);self.assertIn('data-focus="[2]"',output)
        self.assertLess(output.index('<div class="stepper-visual">'),output.index('<ol class="stepper-texts">'))
        self.assertNotIn('data-stepper="motion"',output)
        stepper['visual']={'type':'diagram','caption':'A static drawing.','html':'<svg viewBox="0 0 200 100"><g id="dg-start"><rect width="40" height="40"/></g><path id="dg-arrow" d="M40 20 L180 20"/></svg>'}
        self.assertIn('data-focus="[&quot;dg-start&quot;]"',render(d))
        self.assertIn('data-focus="[&quot;dg-arrow&quot;]"',render(d))
        for focus in ([1],['dg-missing'],['dg-start','dg-start']):
            stepper['steps'][0]['focus']=focus
            with self.subTest(focus=focus),self.assertRaisesRegex(ValueError,'focus needs unique ids'):render(d)
        stepper['steps'][0]['focus']=['dg-start']
        stepper['visual']['html']='<svg><defs><marker id="dg-only"><path d="M0 0L1 1"/></marker></defs></svg>'
        with self.assertRaisesRegex(ValueError,'drawable targets'):render(d)
        stepper['visual']['html']='<div id="dg-duplicate"></div><div id="dg-duplicate"></div>'
        with self.assertRaisesRegex(ValueError,'unique drawable'):render(d)

    def test_walk_hint_only_for_inspectable_mermaid_participants(self):
        import review_mermaid
        d=self.paper();d['layout']='walk'
        self.assertNotIn('Click a diagram participant to inspect it.',render(d))
        source='sequenceDiagram\nA->>B: Read\nB-->>A: Return'
        visual={'type':'mermaid','source':source}
        svg='<svg><g data-et="participant" data-id="A"></g><line data-et="message"/><line data-et="message"/></svg>'
        with patch('review_mermaid.render_all',return_value={review_mermaid.diagram_id(source):svg}):
            stepper=self.stepper();stepper['visual']=visual;d['sections'][0]['blocks']=[stepper]
            self.assertNotIn('Click a diagram participant to inspect it.',render(d))
            d['sections'][0]['blocks'].append(visual)
            self.assertIn('Click a diagram participant to inspect it.',render(d))

    def test_mermaid_stepper_uses_prerendered_message_and_source_node_hooks(self):
        from unittest.mock import patch
        import review_mermaid
        d=self.paper();stepper=self.stepper();d['sections'][0]['blocks']=[stepper]
        source='sequenceDiagram\nA->>B: Read\nB-->>A: Return'
        stepper['visual']={'type':'mermaid','source':source}
        for step in stepper['steps']:del step['focus']
        svg='<svg><line data-et="message"/><path data-et="message"/></svg>'
        with patch('review_mermaid.render_all',return_value={review_mermaid.diagram_id(source):svg}):
            self.assertIn('data-visual="mermaid-sequence"',render(d))
            stepper['steps'][1]['focus']=[3]
            with self.assertRaisesRegex(ValueError,'indices in range'):render(d)
        source='flowchart LR\nA[Read] named@--> B[Return]'
        stepper['visual']['source']=source;stepper['steps'][1].pop('focus')
        svg='<svg><g class="node default" id="mm-test-flowchart-A-0"></g><g class="node" id="mm-test-flowchart-B-1"></g></svg>'
        with patch('review_mermaid.render_all',return_value={review_mermaid.diagram_id(source):svg}):
            output=render(d)
            self.assertIn('data-focus="[&quot;A&quot;]"',output)
            self.assertIn('data-focus="[&quot;B&quot;]"',output)
            self.assertIn('data-edges="{&quot;named&quot;: [&quot;A&quot;, &quot;B&quot;]}"',output)
            stepper['steps'][1]['focus']=['Missing']
            with self.assertRaisesRegex(ValueError,'ids present in the Mermaid source'):render(d)
        stepper['visual']['source']='stateDiagram-v2\n[*] --> Read'
        with patch('review_mermaid.render_all',return_value={}):
            with self.assertRaisesRegex(ValueError,'sequenceDiagram or flowchart'):render(d)

    def test_rejects_manual_numbering_and_supports_absent_cases(self):
        d=self.paper()
        for block in ({'type':'list','items':['1. Read data.']},
                      {'type':'comparison','lanes':[{'title':'Before','steps':['2. Read data.']}]},
                      {**self.stepper(),'steps':[{'label':'Read','text':'1. Read data.'},self.stepper()['steps'][1]]}):
            d['sections'][0]['blocks']=[block]
            with self.assertRaisesRegex(ValueError,'must not start with a number'):render(d)
        d['sections'][0]['blocks']=[{'type':'cases','columns':['Situation','Before','After'],'caption':'Feature availability.',
                                  'rows':[{'situation':'Save filters','cells':[{'status':'absent','text':'No saved presets'},{'status':'works','text':'Apply a preset'}]}]}]
        output=render(d)
        self.assertIn('class="case-absent" data-label="Before"><span class="case-status">Not available</span>: No saved presets',output)
        for layout in ('classic','walk'):
            d['layout']=layout;output=render(d)
            self.assertNotIn('// Reader-advanced visual steps',output)
            self.assertNotIn('/* Layered code walk',output)

    def test_stepper_flow_and_finding_link(self):
        d=self.paper();d['review']['markdown']='<details class="review-finding">\n<summary>P2 · Wrong value</summary>\n\nThe value is wrong.\n\n</details>'
        stepper=self.stepper();stepper['steps'][1]['finding']='Finding 1'
        stepper['visual']={'type':'flow','title':'Data path','caption':'Source trace.','steps':[{'label':'Read','detail':'Read input.'},{'label':'Return','detail':'Return output.'}]}
        d['sections'][0]['blocks']=[stepper]
        output=render(d)
        self.assertIn('href="#finding-1" data-open-finding>⚠ Finding 1</a>',output)
        d['review']['visuals']={'path':stepper}
        d['sections'][0]['blocks']=[]
        d['review']['markdown']=d['review']['markdown'].replace('The value is wrong.', '<!-- review-visual:path -->')
        self.assertIn('class="stepper"',render(d))

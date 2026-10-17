"""Render a fictional parser review with current production assets; no network."""
import _bootstrap
from pathlib import Path
import subprocess
import sys
import tempfile
from render_review import render

BEFORE = '''def parse(values):
    result = []
    for value in values:
        try:
            result.append(int(value))
        except ValueError:
            pass
    return result
'''
AFTER = '''def parse(values):
    try:
        return [int(value) for value in values if value != "0"]
    except ValueError:
        return []
'''


def main():
    output = Path(sys.argv[1])
    with tempfile.TemporaryDirectory(prefix='readme-parser-') as directory:
        repo = Path(directory)
        def git(*args):
            return subprocess.check_output(['git', '-c', 'core.hooksPath=/dev/null',
                '-c', 'commit.gpgsign=false', '-c', 'user.name=Demo',
                '-c', 'user.email=demo@example.invalid', *args], cwd=repo, text=True).strip()
        git('init', '-q')
        source = repo / 'parser.py'
        source.write_text(BEFORE)
        git('add', 'parser.py'); git('commit', '-qm', 'Synthetic base')
        base = git('rev-parse', 'HEAD')
        source.write_text(AFTER)
        git('add', 'parser.py'); git('commit', '-qm', 'Synthetic head')
        head = git('rev-parse', 'HEAD')
        findings = []
        for title, problem, care, steps, real, sketch, comment in [
            ('One bad item empties the whole batch',
             'If one value fails to parse, the parser now returns nothing, including the values that were fine.',
             'Callers importing mixed data silently lose every valid value in that batch.',
             ['The batch is `["12", "bad", "7"]`.', '`int("12")` succeeds inside the list comprehension.',
              '`int("bad")` raises `ValueError`. The catch surrounds the whole comprehension, so it returns `[]` and `"7"` is never read.',
              'Before, the catch sat inside the loop, so the result was `[12, 7]`.'],
             'High confidence from the source trace; not executed. It would only be intentional if batches were meant to be all-or-nothing, which nothing in the change says.',
             'result = []\nfor value in values:\n    try:\n        result.append(int(value))\n    except ValueError:\n        pass\nreturn result',
             'For `["12", "bad", "7"]` we now get `[]`, since the catch wraps the whole comprehension and stops at the first bad value. Should we catch per item instead? Something like:'),
            ('Valid zero values disappear from the result',
             'The new filter drops the value `"0"` even though it is a valid integer.',
             'Any batch containing zero loses it without an error, so totals and counts come out wrong.',
             ['The batch is `["0", "7"]`.', 'The comprehension filter `if value != "0"` rejects `"0"` before conversion.',
              'Only `"7"` is converted, so the result is `[7]` instead of `[0, 7]`.'],
             'High confidence from the source trace. No exception is involved, so fixing the catch does not fix this one.',
             'return [int(value) for value in values]',
             'Could we keep zero values here? For `["0", "7"]` this filter returns `[7]` instead of `[0, 7]`. Something like:'),
        ]:
            walk = '\n'.join(f'{i}. {step}' for i, step in enumerate(steps, 1))
            findings.append(f'''<details class="review-finding">
<summary>P2 · {title}</summary>

**P2 · Comment · Source-verified** · parser.py:3, right side. Synthetic fixture; no GitHub PR.

**The problem in one sentence:** {problem}

**Why you should care:** {care}

**Walk me through it:**

{walk}

**Is it real?** {real}

**How to fix it:** sketch, not a tested patch:

```python
{sketch}
```

<!-- review-comment:start -->
{comment}

```python
{sketch}
```
<!-- review-comment:end -->

<details>
<summary>Evidence and remediation check</summary>

Compared both synthetic revisions of parser.py. Runtime tests were not run.

</details>

</details>''')
        before = 'flowchart LR\n  V[Next value] --> T{int value?}\n  T -->|ok| K[Keep the number]\n  T -->|ValueError| S[Skip it and go on]'
        after = 'flowchart LR\n  V[Next value] --> Z{value is zero?}\n  Z -->|yes| D[Dropped]\n  Z -->|no| T{int value?}\n  T -->|ok| K[Keep the number]\n  T -->|ValueError| E[Return an empty list]'
        data = {'title': 'A shorter parser changes how invalid items are handled', 'layout': 'paper', 'mode': 'Brief · Small',
            'why': {'text': 'The item-by-item loop was hard to read, so the author asked for one list comprehension with the same results.',
                    'sources': [{'label': 'Synthetic PR description'}], 'inferred': False},
            'outcome': 'Clean batches parse as before. One malformed value now empties the whole batch, and valid zero values are dropped.',
            'stack': 'Python · Synthetic review preview', 'repository': str(repo), 'stats': {'additions': 3, 'deletions': 6, 'files': 1},
            'base': base, 'head': head, 'context': 'Fictional parser and review; no real GitHub PR.',
            'glance': {'kind': 'logic', 'kind_label': 'Parser error handling', 'blast': 'moderate',
                       'blast_reason': 'Every caller passing mixed or zero values.',
                       'judgment': [{'text': 'Should callers learn which values were skipped, instead of a silent skip?', 'section': 'change'}]},
            'orientation': {'open': True, 'teaser': 'Where parse() sits between the import and the totals',
                'map': [{'label': 'CSV import', 'name': 'import_rows', 'changed': False}, {'label': 'Number parser', 'name': 'parse(values)', 'changed': True},
                        {'label': 'Totals report', 'name': 'summarize', 'changed': False}],
                'story': 'Imports pass each column to parse(), which skipped any value it could not read and kept the rest.'},
            'sections': [
                {'id': 'change', 'title': 'The change', 'claim': 'One bad value now ends the whole batch, and zeros disappear',
                 'approach': {'text': 'A comprehension cannot catch per item, so the catch moved around the whole list; a small helper that returns None for bad values would keep the old results.', 'suggested': True},
                 'blocks': [{'type': 'paragraph', 'text': 'The loop converted each value inside its own try, so a bad value was skipped. The comprehension converts everything inside one try, so the first bad value returns an empty list. A new filter also removes "0" before conversion.'},
                    {'type': 'compare', 'panes': [
                        {'label': 'Before · one value at a time', 'tone': 'before', 'blocks': [{'type': 'mermaid', 'source': before}]},
                        {'label': 'After · one comprehension', 'tone': 'after', 'blocks': [{'type': 'mermaid', 'source': after}]}],
                     'caption': 'Source-traced from both revisions; not executed.'},
                    {'type': 'cases', 'columns': ['Situation', 'Before', 'After'], 'caption': 'Source-traced for the batch ["12", "bad", "0", "7"] and its parts; not executed.',
                     'rows': [
                        {'situation': 'All values valid', 'cells': [{'status': 'works', 'text': 'all numbers'}, {'status': 'works', 'text': 'all numbers'}]},
                        {'situation': 'One bad value in the batch', 'finding': 'Finding 1', 'cells': [{'status': 'works', 'text': 'bad value skipped'}, {'status': 'breaks', 'text': 'empty result'}]},
                        {'situation': 'Batch contains zero', 'finding': 'Finding 2', 'cells': [{'status': 'works', 'text': 'zero kept'}, {'status': 'breaks', 'text': 'zero dropped'}]}]}]},
                {'id': 'code', 'title': 'Code changes in plain words', 'claim': 'The per-item catch became one outer catch with a zero filter',
                 'blocks': [{'type': 'code_walk', 'items': [
                    {'path': 'parser.py', 'text': 'The loop with a catch per value became one comprehension inside a single catch (Finding 1).',
                     'diff': [{'type': 'source', 'path': 'parser.py', 'side': 'base', 'start': 1, 'end': 8, 'open': True,
                               'caption': 'Before: each value had its own catch.'},
                              {'type': 'source', 'path': 'parser.py', 'side': 'head', 'start': 1, 'end': 5, 'open': True,
                               'caption': 'After: one catch covers the whole list.'}]},
                    {'path': 'parser.py', 'text': 'The new filter compares the text with "0" before conversion, so zero never reaches int() (Finding 2).',
                     'diff': [{'type': 'source', 'path': 'parser.py', 'side': 'head', 'start': 3, 'end': 3,
                               'caption': 'The filter runs on the text, before conversion.'}]}]}]},
                {'id': 'blast', 'title': 'Blast radius', 'claim': 'Only callers that pass mixed or zero values see a change',
                 'blocks': [{'type': 'compare', 'panes': [
                    {'label': 'Not in the blast', 'tone': 'safe', 'blocks': [{'type': 'paragraph', 'text': 'Clean batches: all-valid, zero-free input parses as before.'}]},
                    {'label': 'In the blast', 'tone': 'risk', 'blocks': [
                        {'type': 'paragraph', 'text': 'Mixed imports: one bad value empties the batch (Finding 1).'},
                        {'type': 'paragraph', 'text': 'Totals and counts: zeros vanish without an error (Finding 2).'}]}]},
                    {'type': 'card', 'icon': 'flag', 'name': 'Merge gate', 'tone': 'gate', 'role': 'Do not merge until bad values are skipped per item and zeros are kept.'}]}],
            'questions': [{'question': 'What does the new parser return for ["3", "x"]?', 'options': ['[3]', '[]', 'It raises ValueError'], 'answer': 1,
                           'explanation': 'int("x") raises inside the comprehension; the outer catch returns an empty list.'}],
            'review': {'base': base, 'head': head,
                'assessment': 'Two source-verified P2 defects. Preserve per-item error handling and retain zeros before merging. Runtime tests were not run.',
                'markdown': '\n\n'.join(findings)},
            'verification': '## Coverage and checks\n\nBoth synthetic revisions of parser.py were source-traced. No runtime checks or independent reviewer pass; this is a renderer demonstration.',
            'evidence': {'check': 'Source trace of the complete five-line head against the eight-line base.'}}
        output.write_text(render(data))


if __name__ == '__main__':
    main()

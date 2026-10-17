"""Pre-render Mermaid diagrams in a report input to sanitized static SVG.

Reports never ship Mermaid (3+ MB). The diagrams are rendered once with the
pinned Mermaid in ``report-runtime`` and the installed Chrome, cleaned by the
``review_diagram`` allowlist and themed by the report CSS through Mermaid's
class names. A syntax error fails the render with Mermaid's own message, so the
author can fix the source and render again.
"""
import hashlib
import json
import re
from pathlib import Path
import subprocess

from review_diagram import sanitize_mermaid
import pr_review_tracker as tracker

RUNTIME = Path(__file__).resolve().parent / 'report-runtime'
KINDS = ('sequenceDiagram', 'flowchart', 'graph', 'stateDiagram-v2', 'stateDiagram')
MAX_SOURCE = 6000
# Bump when the runtime config or sanitizer changes, so cached SVGs are re-rendered.
RENDER_VERSION = 2


def diagram_id(source):
    return 'mm-' + hashlib.sha256(source.encode()).hexdigest()[:12]


def sources(data):
    """Every Mermaid block in the narrative sections and the review's visuals."""
    found = {}
    def walk(value):
        if isinstance(value, dict):
            if value.get('type') == 'mermaid':
                source = value.get('source')
                if not isinstance(source, str) or not source.strip().startswith(KINDS):
                    raise ValueError(f'A Mermaid source must start with one of {", ".join(KINDS)}')
                if len(source) > MAX_SOURCE:
                    raise ValueError(f'Keep a Mermaid diagram under {MAX_SOURCE} characters')
                found[diagram_id(source)] = source
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
    walk(data.get('sections', []))
    walk(data.get('review', {}).get('visuals', {}))
    return found


def cache_dir():
    # A sandboxed reviewer may be unable to write the tracker; render uncached then.
    try:
        path = tracker.tracker_root() / 'cache' / 'mermaid'
        path.mkdir(parents=True, exist_ok=True)
        return path
    except OSError:
        return None


def run_runtime(items):
    if not (RUNTIME / 'node_modules' / 'mermaid').exists():
        raise ValueError(f'Mermaid blocks need the report runtime: run `npm ci --prefix {RUNTIME}`')
    try:
        run = subprocess.run(['node', str(RUNTIME / 'render_mermaid.cjs')], input=json.dumps(items), text=True,
                             capture_output=True, cwd=RUNTIME, timeout=180)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ValueError(f'Mermaid rendering could not run: {error}') from None
    if run.returncode:
        detail = (run.stderr.strip().splitlines() or ['no output'])[0][:300]
        raise ValueError(f'Mermaid rendering failed: {detail}')
    return json.loads(run.stdout)


WRAPPED_ROW = re.compile(r'(?<=[^\s>])(</tspan></tspan><tspan class="text-outer-tspan)')


def spaced_rows(svg):
    """Keep a space between wrapped label rows so text extraction doesn't join words."""
    return WRAPPED_ROW.sub(r' \1', svg)


def render_all(data):
    """Map each diagram id to sanitized SVG, rendering only what the cache lacks."""
    found = sources(data)
    if not found:
        return {}
    cache, result, missing = cache_dir(), {}, []
    for ident, source in found.items():
        cached = cache / f'{ident}-v{RENDER_VERSION}.svg' if cache else None
        if cached and cached.exists():
            result[ident] = spaced_rows(sanitize_mermaid(cached.read_text()))
        else:
            missing.append({'id': ident, 'source': source})
    if missing:
        rendered = run_runtime(missing)
        for item in missing:
            output = rendered.get(item['id'], {})
            if 'svg' not in output:
                start = item['source'].strip().splitlines()[0][:60]
                raise ValueError(f'Mermaid syntax error in the diagram starting “{start}”: {output.get("error", "no output").removeprefix("page.evaluate: ")[:300]}')
            svg = sanitize_mermaid(output['svg'])
            result[item['id']] = spaced_rows(svg)
            if cache:
                try:
                    (cache / f'{item["id"]}-v{RENDER_VERSION}.svg').write_text(svg)
                except OSError:
                    pass
    return result

"""Dependency-free block rendering for local review artifacts; raw HTML is escaped."""

import re
from urllib.parse import unquote

START = '<!-- review-comment:start -->'
END = '<!-- review-comment:end -->'
FINDING = '<details class="review-finding">'
DETAILS = ('<details>', FINDING)
FENCE = re.compile(r'^\s*(`{3,}|~{3,})(.*)$')
ITEM = re.compile(r'^(\s*)([-+*]|\d+[.)])\s+(.*)$')
PLACEMENT = re.compile(r'https://github\.com/[\w.-]+/[\w.-]+/blob/[0-9a-f]{40}/([^#)\s]+)#L([1-9][0-9]*)(?:-L([1-9][0-9]*))?')


def finding_locations(lines):
    """Return repository paths and line ranges from a finding's metadata line."""
    summary_seen = False
    fence = None
    for line in lines:
        stripped = line.strip()
        match = FENCE.match(line)
        if match:
            token = match[1]
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence) and not match[2].strip():
                fence = None
            continue
        if fence:
            continue
        if not summary_seen:
            if re.fullmatch(r'<summary>.*</summary>', stripped):
                summary_seen = True
            continue
        if stripped.startswith('**'):
            locations = []
            for match in PLACEMENT.finditer(stripped):
                path = unquote(match[1])
                start, end = int(match[2]), int(match[3] or match[2])
                if (path and not path.startswith('/') and not any(part in ('.', '..') for part in path.split('/'))
                        and not any(ord(char) < 32 for char in path) and start <= end):
                    location = f'{path}:{start}' + (f'-{end}' if end != start else '')
                    if location not in locations:
                        locations.append(location)
            return locations
    return []


def handoff_prompt(body, locations):
    """Build a plain-text prompt without the GitHub-comment attribution footer."""
    location = ', '.join(locations) if locations else 'not specified (general PR feedback)'
    return f'Please address this review feedback.\n\nFile and line: {location}\n\nFeedback:\n{body}'


def find_close(lines, start, end_marker):
    fence = None
    depth = 0
    for i in range(start, len(lines)):
        s = lines[i].strip()
        m = FENCE.match(lines[i])
        if m:
            token = m[1]
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence) and not m[2].strip():
                fence = None
            continue
        if fence:
            continue
        if end_marker == '</details>' and s in DETAILS:
            depth += 1
        elif s == end_marker:
            if depth == 0:
                return i
            depth -= 1
    return None


def cells(line):
    # Ignore escaped pipes and pipes inside inline code spans.
    result, current, fence = [], [], 0
    s = line.strip().strip('|')
    i = 0
    while i < len(s):
        c = s[i]
        if c == '\\' and i + 1 < len(s) and s[i + 1] == '|':
            current.append('|'); i += 2; continue
        if c == '`':
            j = i
            while j < len(s) and s[j] == '`': j += 1
            width = j - i
            fence = 0 if fence == width else (width if not fence else fence)
            current.append(s[i:j]); i = j; continue
        if c == '|' and not fence:
            result.append(''.join(current).strip()); current = []
        else:
            current.append(c)
        i += 1
    result.append(''.join(current).strip())
    return result


def render(text, inline, escape, depth=0, visual=None, footer='', handoff_locations=None, handoff_enabled=False):
    if depth > 24:
        return '<pre>' + escape(text) + '</pre>'
    lines = text.replace('\r\n', '\n').split('\n')
    parts, i = [], 0
    def sub(body, allow_visual=True, locations=None):
        context = handoff_locations if locations is None else locations
        return render('\n'.join(body), inline, escape, depth + 1, visual if allow_visual else None, footer, context, handoff_enabled)
    def table_at(index):
        if index + 1 >= len(lines) or '|' not in lines[index]: return False
        cols, delimiters = cells(lines[index]), cells(lines[index + 1])
        return len(cols) == len(delimiters) and all(re.fullmatch(r':?-{3,}:?', c) for c in delimiters)
    def begins(index):
        s = lines[index].strip()
        return (not s or FENCE.match(lines[index]) or ITEM.match(lines[index])
                or re.match(r'^(#{1,6})\s|^>', s) or s in (START, *DETAILS, '---', '***', '___')
                or re.fullmatch(r'<!-- review-visual:[a-z][a-z0-9-]* -->', s) or table_at(index))
    while i < len(lines):
        line, s = lines[i], lines[i].strip()
        if not s:
            i += 1; continue
        fence = FENCE.match(line)
        if fence:
            token, language = fence[1], fence[2].strip()
            block, i = [], i + 1
            while i < len(lines):
                m = FENCE.match(lines[i])
                if m and m[1][0] == token[0] and len(m[1]) >= len(token) and not m[2].strip():
                    i += 1; break
                block.append(lines[i]); i += 1
            parts.append('<pre><code>' + escape('\n'.join(block)) + '</code></pre>')
        elif s == START and (end := find_close(lines, i + 1, END)) is not None:
            body = '\n'.join(lines[i + 1:end]).strip('\n')
            actions = '<button type="button" class="copy-comment">Copy comment</button>'
            handoff_source = ''
            if handoff_enabled:
                prompt = handoff_prompt(body, handoff_locations or [])
                actions += ' <button type="button" class="copy-handoff">Copy handoff prompt</button>'
                handoff_source = '<textarea class="handoff-source" hidden readonly aria-label="Handoff prompt">' + escape(prompt) + '</textarea>'
            if footer: body += '\n\n' + footer
            parts.append('<section class="review-comment">' + actions
                         + '<span class="copy-status" role="status"></span><div class="comment-body">'
                         + sub(body.split('\n'), allow_visual=False) + '</div><textarea class="comment-source" hidden readonly aria-label="Comment Markdown">'
                         + escape(body) + '</textarea>' + handoff_source + '</section>')
            i = end + 1
        elif visual and (marker := re.fullmatch(r'<!-- review-visual:([a-z][a-z0-9-]*) -->', s)):
            parts.append(visual(marker[1])); i += 1
        elif s in DETAILS and (end := find_close(lines, i + 1, '</details>')) is not None:
            start = i + 1
            while start < end and not lines[start].strip(): start += 1
            summary = re.fullmatch(r'<summary>(.*?)</summary>', lines[start].strip()) if start < end else None
            if summary:
                locations = finding_locations(lines[start:end]) if s == FINDING else None
                parts.append(s + '<summary>' + inline(summary[1]) + '</summary>' + sub(lines[start + 1:end], locations=locations) + '</details>')
                i = end + 1
            else:
                parts.append('<p>' + escape(line) + '</p>'); i += 1
        elif s.startswith('>'):
            block = []
            while i < len(lines) and lines[i].lstrip().startswith('>'):
                block.append(re.sub(r'^\s*> ?', '', lines[i], count=1)); i += 1
            parts.append('<blockquote>' + sub(block) + '</blockquote>')
        elif table_at(i):
            headers, align = cells(lines[i]), cells(lines[i + 1])
            width = len(headers)
            styles = ['center' if c.startswith(':') and c.endswith(':') else 'right' if c.endswith(':') else 'left' for c in align]
            def row(cols, tag):
                cols = (cols + [''] * width)[:width]
                return '<tr>' + ''.join(f'<{tag} style="text-align:{styles[n]}">{inline(c)}</{tag}>' for n, c in enumerate(cols)) + '</tr>'
            output = ['<div class="table-scroll"><table><thead>', row(headers, 'th'), '</thead><tbody>']
            i += 2
            while i < len(lines) and lines[i].strip() and '|' in lines[i]:
                output.append(row(cells(lines[i]), 'td')); i += 1
            output.append('</tbody></table></div>'); parts.append(''.join(output))
        elif heading := re.match(r'^(#{1,6})\s+(.*)$', s):
            level = len(heading[1]); parts.append(f'<h{level}>{inline(heading[2])}</h{level}>'); i += 1
        elif s in ('---', '***', '___'):
            parts.append('<hr>'); i += 1
        elif item := ITEM.match(line):
            indent = len(item[1]); ordered = item[2][0].isdigit(); tag = 'ol' if ordered else 'ul'
            items = []
            while i < len(lines):
                m = ITEM.match(lines[i])
                if not m or len(m[1]) != indent or m[2][0].isdigit() != ordered: break
                content_indent = len(m[1]) + len(m[2]) + 1
                content = [m[3]]; i += 1
                while i < len(lines):
                    if not lines[i].strip():
                        # Keep a blank only when the following line continues this item.
                        j = i + 1
                        while j < len(lines) and not lines[j].strip(): j += 1
                        if j < len(lines) and len(lines[j]) - len(lines[j].lstrip()) > indent:
                            content.append(''); i += 1; continue
                        break
                    spaces = len(lines[i]) - len(lines[i].lstrip())
                    if spaces <= indent: break
                    content.append(lines[i][min(content_indent, spaces):]); i += 1
                items.append('<li>' + sub(content) + '</li>')
                while i < len(lines) and not lines[i].strip(): i += 1
            parts.append(f'<{tag}>' + ''.join(items) + f'</{tag}>')
        else:
            paragraph = [line]; i += 1
            while i < len(lines) and not begins(i):
                paragraph.append(lines[i]); i += 1
            parts.append('<p>' + inline(' '.join(paragraph)) + '</p>')
    return '\n'.join(parts)

"""Validate layout-model headings against the document's structural evidence."""
import re
import unicodedata

from docvortex.document.pdf import PDFDocument

from .source import visible_text_lines


SECTION = re.compile(r'^\s*((?:\d+|[A-Z])(?:\.\d+)*\.?|[IVXLCDM]+\.)\s+(?=\S)')
COMMON_HEADINGS = {
    'abstract', 'reference', 'references', 'bibliography', 'acknowledgments',
    'acknowledgements', 'appendix', 'appendices', 'supplementarymaterial',
    '摘要', '参考文献', '致谢', '附录',
}


def text_content(content):
    if isinstance(content, str):
        return content
    return ''.join(text_content(part.get('content', '')) for part in content)


def title_key(text):
    text = unicodedata.normalize('NFKC', text)
    text = SECTION.sub('', text, count=1)
    return ''.join(c for c in text.casefold() if c.isalnum())


def read_outline(pdf):
    outline = []
    for bookmark in pdf.get_toc():
        destination = bookmark.get_dest()
        page = destination.get_index() if destination else None
        key = title_key(bookmark.get_title())
        if page is not None and key:
            outline.append((page, key, bookmark.level + 1))
    return outline


def _text_nodes(nodes):
    for node in nodes:
        if node['type'] in ('list', 'index'):
            yield from _text_nodes(node['content'])
        elif node['type'] in ('paragraph_title', 'text'):
            yield node
        # Visual containers own their children. Their labels are never sections.


def _box(node, size):
    return [v * scale for v, scale in zip(node['bbox'], (size['width'], size['height']) * 2, strict=True)]


def _lines_for_heading(node, size, lines):
    if not node.get('bbox'):
        return []
    x0, y0, x1, y1 = _box(node, size)
    result = []
    for line in lines:
        left, top, right, bottom = line['bbox']
        # Include a detached section number, but never reach across a column.
        text = ''.join(span['text'] for span in line['spans']).strip()
        detached_number = bool(re.fullmatch(r'(?:\d+|[A-Z])(?:\.\d+)*\.?|[IVXLCDM]+\.', text))
        if (y0 - 2 <= (top + bottom) / 2 <= y1 + 2
                and x0 - 2.5 * (bottom - top) <= left < x1
                and (min(right, x1) - max(left, x0) > 0 or detached_number)):
            result.append(line)
    return sorted(result, key=lambda line: (round(line['bbox'][1] / 3), line['bbox'][0]))


def _font_spans(lines):
    return [span for line in lines for span in line['spans'] if span['text'].strip()]


def _bold(span):
    font = span.get('font', {})
    return font.get('weight', 0) >= 600 or bool(re.search(r'bold|demi|black', font.get('name', ''), re.I))


def _set_bold(content):
    if isinstance(content, str):
        return [{'type': 'text', 'content': content, 'styles': ['bold']}]
    for part in content:
        if part['type'] == 'hyperlink':
            part['content'] = _set_bold(part['content'])
        elif part['type'] == 'text':
            part['styles'] = list(dict.fromkeys([*part.get('styles', []), 'bold']))
    return content


def refine_headings(pages, sizes, path, outline, check_cancel):
    """Finish all structural changes before translation/search receive any blocks.

    Bookmarks are useful only after they agree with the actual extracted titles.
    A partial outline must not silently discard unbookmarked subsections. Without
    a usable outline, retain model headings unless native text supplies positive
    evidence of a run-in label or a multi-sentence paragraph.
    """
    entries = [(page['page_idx'], node) for page in pages
               for node in _text_nodes(page.get('blocks', []))]
    outline_map = {(page, key): level for page, key, level in outline}
    matched = {(page, title_key(text_content(node['content']))) for page, node in entries
               if (page, title_key(text_content(node['content']))) in outline_map}
    numbered = [(page, node) for page, node in entries
                if node['type'] == 'paragraph_title' and SECTION.match(text_content(node['content']))]
    numbered_matches = sum((page, title_key(text_content(node['content']))) in matched
                           for page, node in numbered)
    complete_outline = (len(matched) >= 3 and len(matched) >= .8 * len(outline_map)
                        and len(numbered) >= 3 and numbered_matches == len(numbered))

    by_page = {}
    for page, node in entries:
        key = title_key(text_content(node['content']))
        if node['type'] == 'paragraph_title' or (page, key) in matched:
            by_page.setdefault(page, []).append(node)

    with PDFDocument(str(path)) as document:
        for page, nodes in by_page.items():
            check_cancel()
            lines = visible_text_lines(document, page)
            for node in nodes:
                text = text_content(node['content'])
                key = title_key(text)
                level = outline_map.get((page, key))
                native = _lines_for_heading(node, sizes[page], lines)
                native_text = ' '.join(''.join(s['text'] for s in line['spans']).strip() for line in native)
                prefix = SECTION.match(native_text)
                # Copy only a number that is actually printed beside this title.
                # Bookmark order and neighbouring section numbers never invent it.
                if not SECTION.match(text) and prefix and title_key(native_text) == key:
                    label = prefix.group(0).strip() + ' '
                    if isinstance(node['content'], str):
                        node['content'] = label + node['content']
                    else:
                        node['content'].insert(0, {'type': 'text', 'content': label})
                    node['bbox'][0] = min(node['bbox'][0], min(line['bbox'][0] for line in native) / sizes[page]['width'])
                    text = label + text
                number = SECTION.match(text)
                spans = _font_spans(native)
                source_key = title_key(native_text)
                run_in = bool(key) and source_key.startswith(key) and len(source_key) > len(key) + 8
                prose = len(text.split()) > 25 and bool(re.search(r'[.!?]\s+\S', text))
                if level is not None:
                    node.update(type='paragraph_title', level=level)
                elif key not in COMMON_HEADINGS and (run_in or prose or (complete_outline and not number)):
                    node['type'] = 'text'
                    node.pop('level', None)
                    if spans and all(_bold(s) for s in spans):
                        node['content'] = _set_bold(node['content'])
                elif number:
                    node['level'] = number.group(1).rstrip('.').count('.') + 1

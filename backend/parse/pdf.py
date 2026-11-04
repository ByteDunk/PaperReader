"""Adapt MinerU blocks to PaperReader; all source boxes use PDF points."""
from concurrent.futures import CancelledError
from contextlib import closing
from copy import deepcopy
from pathlib import Path
from math import isfinite, sqrt

import pypdfium2 as pdfium
from docvortex.document.pdf.pdfium import pdfium_guard

from .mineru_runtime import parse_document
from .headings import read_outline, refine_headings

PARSER_VERSION = 9


def pdf_info(path):
    with pdfium_guard(), pdfium.PdfDocument(str(path)) as pdf:
        return {**pdf.get_metadata_dict(), 'pages': len(pdf)}


def render_region(path, page_index, bbox, destination, scale=2):
    if not isfinite(scale) or not 1 <= scale <= 8:
        raise ValueError('无效的图片渲染倍率。')
    with pdfium_guard(), pdfium.PdfDocument(str(path)) as pdf:
        with closing(pdf[page_index]) as page:
            width, height = page.get_size()
            x0, y0, x1, y1 = bbox or (0, 0, width, height)
            crop = (max(0, x0 - 2), max(0, height - y1 - 2),
                    max(0, width - x1 - 2), max(0, y0 - 2))
            clipped_width, clipped_height = width - crop[0] - crop[2], height - crop[1] - crop[3]
            # Bound a single bitmap even for unusually large PDF pages.
            scale = min(scale, sqrt(32_000_000 / (clipped_width * clipped_height)),
                        8192 / clipped_width, 8192 / clipped_height)
            with closing(page.render(scale=scale, crop=crop)) as bitmap:
                image = bitmap.to_pil().copy()
    try:
        image.save(destination)
    finally:
        image.close()


def point_box(bbox, width, height):
    return [round(v * size, 3) for v, size in zip(bbox, (width, height, width, height), strict=True)]


def extract_pdf(path, assets_dir, on_progress=None, on_blocks=None, is_cancelled=lambda: False):
    assets_dir = Path(assets_dir)
    assets_dir.mkdir(parents=True, exist_ok=True)

    def check_cancel():
        if is_cancelled():
            raise CancelledError()

    check_cancel()
    if on_progress:
        on_progress(0)
    parsed, formulas = parse_document(path, on_progress, is_cancelled)
    check_cancel()
    with pdfium_guard(), pdfium.PdfDocument(str(path)) as pdf:
        metadata = pdf.get_metadata_dict()
        outline = read_outline(pdf)
        pages = []
        for index in range(len(pdf)):
            with closing(pdf[index]) as page:
                width, height = page.get_size()
            pages.append({'number': index + 1, 'width': width, 'height': height})

    document_pages = parsed.to_dict()['pages']
    refine_headings(document_pages, pages, path, outline, check_cancel)

    blocks, warnings = [], []
    asset_count = 0
    asset_regions = {}

    def asset(page, bbox):
        nonlocal asset_count
        check_cancel()
        asset_count += 1
        name = f'p{page}-b{asset_count}.png'
        asset_regions[name] = {'page': page, 'bbox': bbox}
        render_region(path, page - 1, bbox, assets_dir / name)
        return name

    def rich_text(content, page, bbox):
        if isinstance(content, str):
            return content, [{'text': content, 'bold': False}] if content else []
        spans = []
        for node in content:
            if node['type'] == 'hyperlink':
                spans.extend(rich_text(node['content'], page, bbox)[1])
                continue
            styles = node.get('styles', [])
            span = {'text': node['content'], 'bold': 'bold' in styles}
            if 'subscript' in styles or 'superscript' in styles:
                span['script'] = 'sub' if 'subscript' in styles else 'sup'
            if node['type'] == 'equation_inline':
                candidates = formulas.get(page - 1, [])
                match = next((item for item in candidates
                              if ''.join(item['text'].split()) == ''.join(span['text'].split())
                              and bbox[0] - 2 <= (item['bbox'][0] + item['bbox'][2]) / 2 <= bbox[2] + 2
                              and bbox[1] - 2 <= (item['bbox'][1] + item['bbox'][3]) / 2 <= bbox[3] + 2), None)
                if match:
                    span.update(asset=asset(page, match['bbox']),
                                display_width=round(match['bbox'][2] - match['bbox'][0] + 4, 2))
                    candidates.remove(match)
            spans.append(span)
        return ''.join(span['text'] for span in spans), spans

    def convert(node, page, width, height, parent_bbox=None):
        kind = node['type']
        if kind in ('header', 'footer', 'page_number', 'aside_text'):
            return
        bbox = point_box(node['bbox'], width, height) if node.get('bbox') else parent_bbox
        if kind in ('list', 'index'):
            for child in node['content']:
                convert(child, page, width, height, bbox)
            return
        block = {'id': f'p{page}-b{len(blocks) + 1}', 'page': page, 'bbox': bbox,
                 'sources': [{'page': page, 'bbox': bbox}]}
        if kind in ('image', 'table', 'chart', 'code'):
            block['type'] = 'table' if kind == 'table' else 'figure'
            block['asset'] = asset(page, bbox)
            caption_spans = []
            for child in node['content']:
                if child['type'].endswith(('_caption', '_footnote')):
                    child_bbox = point_box(child['bbox'], width, height) if child.get('bbox') else bbox
                    text, spans = rich_text(child['content'], page, child_bbox)
                    if caption_spans and text:
                        caption_spans.append({'text': '\n', 'bold': False})
                    caption_spans.extend(spans)
                    block['sources'].append({'page': page, 'bbox': child_bbox})
            block.update(caption=''.join(s['text'] for s in caption_spans), caption_spans=caption_spans)
        elif kind == 'equation':
            block.update(type='equation', text=node['content'], asset=asset(page, bbox),
                         display_width=round(bbox[2] - bbox[0] + 4, 2))
        else:
            text, spans = rich_text(node['content'], page, bbox)
            if not text.strip():
                return
            block.update(type={'doc_title': 'title', 'paragraph_title': 'heading',
                               'page_footnote': 'footnote'}.get(kind, 'paragraph'), text=text, spans=spans)
            if 'level' in node:
                block['level'] = node['level']
            if node.get('continues_prev') and block['type'] == 'paragraph':
                previous = next((b for b in reversed(blocks) if b['type'] == 'paragraph'), None)
                if previous:
                    # Continuation is decided by MinerU, never guessed from PDF fonts or gaps.
                    separator = '' if previous['text'].endswith((' ', '-', '\n')) else ' '
                    previous['text'] += separator + text
                    if separator:
                        previous['spans'].append({'text': separator, 'bold': False})
                    previous['spans'].extend(spans)
                    previous['sources'].extend(block['sources'])
                    return
        blocks.append(block)

    published = 0
    for page in document_pages:
        check_cancel()
        info = pages[page['page_idx']]
        for node in page.get('blocks', []):
            convert(node, info['number'], info['width'], info['height'])
        if not page.get('blocks'):
            warnings.append(f"第 {info['number']} 页未识别出内容，请对照原文阅读。")
        # Retain the last paragraph until later pages have applied continues_prev.
        stable = next((i for i in range(len(blocks) - 1, -1, -1)
                       if blocks[i]['type'] == 'paragraph'), len(blocks))
        if on_blocks and stable > published:
            on_blocks(deepcopy(blocks[published:stable]))
            published = stable
        if on_progress:
            on_progress(90 + int(info['number'] / (len(pages) + 1) * 9))
    check_cancel()
    if on_blocks and published < len(blocks):
        on_blocks(deepcopy(blocks[published:]))
    if on_progress:
        on_progress(99)
    title = next((b['text'] for b in blocks if b['type'] == 'title'), '')
    return {'blocks': blocks, 'pages': pages, 'warnings': warnings, 'assets': asset_regions,
            'title': title or metadata.get('Title', ''), 'authors': metadata.get('Author', '')}

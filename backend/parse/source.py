"""Visible PDF text evidence shared by extraction and heading validation."""
from contextlib import contextmanager
from dataclasses import replace
from unittest.mock import patch

from docvortex.document.pdf import PDFDocument, PDFPageTextGeometry
from docvortex.document.pdf.pdfium import pdfium_guard
from docvortex.document.pdf.text import get_lines_from_chars


def _clean_clipped_separators(text):
    if not isinstance(text, PDFPageTextGeometry):
        # Keep the fast native path when clipping did not remove any characters.
        if text.raw_char_count() == text.info()[0]:
            return text
        geometry = text.materialize_geometry()
    else:
        geometry = text
    printed = {c['char_idx'] for c in geometry.chars if not c['char'].isspace()}

    def keep(char):
        if not (char.get('is_generated') and char.get('text_object_id') is None and char['char'].isspace()):
            return True
        index = char['char_idx']
        # PDFium's synthetic separators have no text object or clip of their
        # own. Retain them only beside retained source glyphs (CRLF uses two
        # indices). Otherwise they can still split words in the other column.
        before = any(index - offset in printed for offset in (1, 2))
        after = any(index + offset in printed for offset in (1, 2))
        return before and (after or char['char'] in '\r\n')

    chars = [char for char in geometry.chars if keep(char)]
    if len(chars) == len(geometry.chars):
        return text
    retained = {c['char_idx'] for c in chars}
    return replace(geometry, chars=chars,
                   **{name: {i: value for i, value in getattr(geometry, name).items() if i in retained}
                      for name in ('tight_bboxes', 'origins', 'loose_bboxes')})


@contextmanager
def visible_pdf_text():
    # DocVortex's Hybrid snapshots default to visible_only=False. A
    # cropped Form can then contribute its entire, repeated text outside the
    # clip, even in another column. Apply clipping BEFORE grouping characters
    # into lines; deleting strings from finished paragraphs cannot repair it.
    # The caller holds MINERU_LOCK for the entire scoped patch.
    extract = PDFDocument._extract_owned_text_snapshot

    def visible(document, page_idx, page, *, visible_only, materialize=True):
        text = extract(document, page_idx, page, visible_only=True, materialize=materialize)
        return _clean_clipped_separators(text) if text is not None else None

    def geometry(document, page_idx, *, include_extended_geometry):
        # The Python compute backend uses this older geometry entry point.
        with pdfium_guard(), document._open_page(page_idx) as page:
            text = visible(document, page_idx, page, visible_only=True)
        return text if isinstance(text, PDFPageTextGeometry) else text.materialize_geometry()

    with patch.object(PDFDocument, '_extract_owned_text_snapshot', visible), \
            patch.object(PDFDocument, '_get_page_text_geometry', geometry):
        yield


def visible_text_lines(document, page_idx):
    """Read text without vectors/images, respecting page rotation and Form clips."""
    with pdfium_guard(), document._open_page(page_idx) as page:
        text = document._extract_owned_text_snapshot(page_idx, page, visible_only=True)
    if text is not None:
        text = _clean_clipped_separators(text)
    if isinstance(text, PDFPageTextGeometry):
        return get_lines_from_chars(text.chars)
    return text.prepare_grouped_evidence(0.7, 0.1)[1] if text is not None else []

"""Pinned MinerU ONNX pipeline, with table recognition disabled."""
import os
import threading
from concurrent.futures import CancelledError
from contextlib import ExitStack
from unittest.mock import patch

from ..resources import mineru_home, models_dir
from .source import visible_pdf_text

MODELS_DIR = models_dir()
MINERU_LOCK = threading.Lock()


def configure_mineru():
    # Set paths before importing MinerU: its configuration is loaded on import.
    source = 'local' if os.environ.get('PAPERREADER_DESKTOP') == '1' else 'modelscope'
    os.environ.update(MINERU_HOME=str(mineru_home()),
                      MINERU_MODEL_BASE_DIR=str(MODELS_DIR),
                      MINERU_MODEL_SMALL_BACKEND='onnx', MINERU_MODEL_SOURCE=source)
    os.environ.setdefault('MINERU_PROCESSING_WINDOW_SIZE', '4')
    from mineru.config import config
    config.model.base_dir = str(MODELS_DIR)
    config.model.small_backend = 'onnx'
    config.model.source = source


def parse_document(path, on_progress, is_cancelled):
    with MINERU_LOCK:
        return _parse_document(path, on_progress, is_cancelled)


def _parse_document(path, on_progress, is_cancelled):
    configure_mineru()
    from mineru import parse
    from mineru.backend.analysis.pdf import formulas, tables, window

    inline_formulas = {}
    current_page = 0
    process_window = window._process_pdf_window
    process_text = window._process_text_and_formulas
    split_formulas = formulas._split_formula_results

    def check_cancel():
        if is_cancelled():
            raise CancelledError()

    def report_window(file_bytes, document, batch, **options):
        nonlocal current_page
        check_cancel()
        current_page = batch.start
        result = process_window(file_bytes, document, batch, **options)
        check_cancel()
        if on_progress:
            on_progress(int((batch.end + 1) / options['page_count'] * 90))
        return result

    def capture_text(images, *args, **kwargs):
        def capture_formulas(values):
            inline, display = split_formulas(values)
            for offset, (items, page_image) in enumerate(zip(inline, images, strict=True)):
                scale = page_image['scale']
                inline_formulas[current_page + offset] = [
                    {'text': item['latex'], 'bbox': [v / scale for v in item['bbox']]}
                    for item in items if item.get('latex')]
            return inline, display
        with patch.object(formulas, '_split_formula_results', capture_formulas):
            return process_text(images, *args, **kwargs)

    # MinerU 4.0.12 has no public table switch. Disable only its three table
    # stages, retaining layout detection, OCR and both formula recognition paths.
    # The lock and scoped patches prevent concurrent jobs from sharing callbacks.
    with ExitStack() as stack:
        check_cancel()
        stack.enter_context(visible_pdf_text())
        for name, replacement in (
            ('_apply_table_orientations', lambda *a, **k: None),
            ('_apply_medium_table_recognition', lambda *a, **k: None),
            ('_apply_native_txt_table_priority', lambda *a, **k: tables._NativeTablePrioritySummary()),
        ):
            stack.enter_context(patch.object(tables, name, replacement))
        stack.enter_context(patch.object(window, '_process_pdf_window', report_window))
        stack.enter_context(patch.object(window, '_process_text_and_formulas', capture_text))
        result = parse(path, tier='basic', ocr_mode='auto')
        check_cancel()
    return result, inline_formulas

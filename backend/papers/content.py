"""Paper source text, fixed headings and bibliography-section annotation."""
import re
import unicodedata


def source_text(block):
    field = 'caption' if block['type'] in ('figure', 'table') else 'text'
    return block.get(field, '').strip()


COMMON_HEADING = re.compile(
    r'^(?P<prefix>(?:(?:\d+(?:\.\d+)*|[ivxlcdm]+|[一二三四五六七八九十]+)[\s.、:：)）-]+)?)'
    r'(?P<word>abstract|references?|摘要|参考文献)[\s:：.。]*$', re.IGNORECASE)


def fixed_heading_translation(block):
    if block['type'] not in ('title', 'heading', 'paragraph'):
        return None
    text = unicodedata.normalize('NFKC', block.get('text', '')).strip()
    match = COMMON_HEADING.fullmatch(text)
    if not match:
        return None
    label = '摘要' if match['word'].lower() in ('abstract', '摘要') else '参考文献'
    return match['prefix'] + label


REFERENCE_HEADING = re.compile(
    r'^(?:(?:\d+(?:\.\d+)*|[ivxlcdm]+|[一二三四五六七八九十]+)[\s.、:：)）-]+)?'
    r'(?:references?|bibliography|literature cited|works cited|参考文献|引用文献|参考资料)'
    r'[\s:：.。]*$', re.IGNORECASE)


def annotate_references(blocks):
    active, level = False, 1
    for block in blocks:
        text = unicodedata.normalize('NFKC', block.get('text', '')).strip()
        heading = block['type'] in ('heading', 'title')
        if REFERENCE_HEADING.fullmatch(text):
            active, level = True, block.get('level', 1)
        elif heading and active and block.get('level', 1) <= level:
            active = False
        block['is_reference'] = block['type'] == 'reference' or active

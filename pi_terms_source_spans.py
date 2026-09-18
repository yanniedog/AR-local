"""Mechanical locators for untrusted text; these do not establish legal clauses."""
from __future__ import annotations


def source_spans(text: str) -> list[dict]:
    if not isinstance(text, str):
        raise ValueError('source_text must be text')
    # Bound metadata expansion even for a document containing tiny lines.
    width = max(256, (len(text) + 127) // 128)
    spans = []
    start = 0
    while start < len(text):
        end = min(start + width, len(text))
        if end < len(text):
            floor = start + width // 2
            boundary = text.rfind('\n', floor, end)
            if boundary < floor:
                boundary = text.rfind(' ', floor, end)
            if boundary >= floor:
                end = boundary + 1
        spans.append({'start': start, 'end': end, 'text': text[start:end]})
        start = end
    return spans


def prompt_source(job: dict) -> dict:
    """Keep the persisted input/binding unchanged; render its text only once."""
    value = dict(job)
    if 'reviewed_structure' in value:
        return value  # Reviewed page/section locators outrank mechanical chunks.
    text = value.pop('source_text')
    value['source_spans'] = source_spans(text)
    return value

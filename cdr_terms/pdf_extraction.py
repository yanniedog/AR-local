"""Page-bound PDF evidence; text availability never proves legal completeness."""
from __future__ import annotations

import hashlib
import io
import re
from urllib.parse import urljoin, urlsplit

from .discovery import document_url

PDF_POLICY_VERSION = 'pdf-page-evidence-1'
MAX_PDF_BYTES = 16 * 1024**2
MAX_PAGES = 512
MAX_TEXT_CHARACTERS = 2_000_000
MAX_PAGE_CHARACTERS = 100_000
MAX_LINKS = 256
SEPARATOR = '\n\f\n'


class PageTextLimit(Exception):
    pass


def _page_text(page, maximum):
    seen = 0

    def visit(text, *_):
        nonlocal seen
        seen += len(text)
        if seen > maximum:
            raise PageTextLimit()

    text = page.extract_text(visitor_text=visit) or ''
    if len(text) > maximum:
        raise PageTextLimit()
    return text


def _page_links(page, text, page_number, start, source_url, base_requires_review):
    """Candidate references only; never execute actions or guess wrapped URLs."""
    for index, match in enumerate(re.finditer(r'https?://[^\s<>"\x00-\x1f]+', text), 1):
        value = match.group().rstrip('.,;')
        yield {'sourceUrl': value, 'url': document_url(value), 'href': value,
               'page': page_number, 'text_start': start + match.start(),
               'text_end': start + match.start() + len(value), 'label': value[:2000],
               'source_kind': 'pdf_printed_url_candidate', 'occurrence': index}
    for index, reference in enumerate(page.get('/Annots', []), 1):
        try:
            annotation = reference.get_object()
            action = annotation.get('/A')
            if action is None:
                continue
            action = action.get_object()
            if '/S' not in action or action['/S'] != '/URI':
                continue
            resolved_uri = action['/URI'] if '/URI' in action else None
            if not isinstance(resolved_uri, str):
                yield {'sourceUrl': '', 'url': None, 'href': '', 'page': page_number,
                       'label': '', 'source_kind': 'unreadable_pdf_uri', 'annotation_index': index}
                continue
            href = str(resolved_uri)
            if len(href) > 8192:
                yield {'sourceUrl': '', 'url': None, 'href': '', 'page': page_number,
                       'label': '', 'source_kind': 'oversized_pdf_uri', 'annotation_index': index}
                continue
            if base_requires_review and not urlsplit(href).scheme:
                yield {'sourceUrl': href, 'url': None, 'href': href, 'page': page_number,
                       'label': '', 'source_kind': 'pdf_uri_base_requires_review', 'annotation_index': index}
                continue
            value = urljoin(source_url, href)
            yield {'sourceUrl': value, 'url': document_url(value), 'href': href,
                   'page': page_number, 'label': '', 'annotation_index': index,
                   'source_kind': 'pdf_uri_annotation_candidate'}
        except Exception:
            yield {'sourceUrl': '', 'url': None, 'href': '', 'page': page_number,
                   'label': '', 'annotation_index': index, 'source_kind': 'unreadable_pdf_annotation'}


def extract_pdf(body: bytes, source_url: str):
    coverage = {'policy_version': PDF_POLICY_VERSION, 'media_type': 'application/pdf',
                'reason': 'pdf_tables_footnotes_layout_and_ocr_require_review',
                'page_spans': [], 'unreadable_pages': [], 'candidate_links': [],
                'candidate_links_total': 0, 'candidate_links_omitted': 0,
                'layout_status': 'unreviewed', 'table_structure_status': 'unreviewed',
                'footnote_associations_status': 'unreviewed', 'ocr_status': 'not_performed',
                'incorporated_references_status': 'unreviewed'}
    if len(body) > MAX_PDF_BYTES:
        return '', 'failed', {**coverage, 'reason': 'pdf_input_byte_limit'}
    try:
        import pypdf
    except ImportError:
        return '', 'failed', {**coverage, 'reason': 'pdf_extractor_unavailable'}
    coverage['parser_version'] = pypdf.__version__
    try:
        reader = pypdf.PdfReader(io.BytesIO(body))
        if reader.is_encrypted:
            return '', 'failed', {**coverage, 'reason': 'encrypted_pdf'}
        count = len(reader.pages)
    except Exception:
        return '', 'failed', {**coverage, 'reason': 'pdf_extraction_failed'}
    coverage.update(pages=count, pages_processed=0, unprocessed_page_range=None)
    try:
        coverage['pdf_uri_base_requires_review'] = '/URI' in reader.trailer['/Root']
    except Exception:
        coverage['pdf_uri_base_requires_review'] = True
    fragments, offset = [], 0
    for index in range(min(count, MAX_PAGES)):
        if MAX_TEXT_CHARACTERS - offset - len(SEPARATOR) <= 0:
            break
        if fragments:
            fragments.append(SEPARATOR)
            offset += len(SEPARATOR)
        text, state, reason, page = '', 'unreadable', None, None
        try:
            page = reader.pages[index]
            text = _page_text(page, min(MAX_PAGE_CHARACTERS, MAX_TEXT_CHARACTERS - offset))
            state = 'text_available' if text.strip() else 'textless_review_required'
        except PageTextLimit:
            reason = 'page_text_limit'
        except Exception:
            reason = 'page_extraction_failed'
        span = {'page': index + 1, 'start': offset, 'end': offset + len(text),
                'text_sha256': hashlib.sha256(text.encode('utf-8')).hexdigest(),
                'status': state, 'reason': reason,
                'replacement_character_present': '\ufffd' in text}
        coverage['page_spans'].append(span)
        if state != 'text_available':
            coverage['unreadable_pages'].append(index + 1)
        if page is not None:
            _retain_links(coverage, page, text, index + 1, offset, source_url)
        fragments.append(text)
        offset += len(text)
        coverage['pages_processed'] += 1
    if coverage['pages_processed'] < count:
        coverage['unprocessed_page_range'] = [coverage['pages_processed'] + 1, count]
    coverage['candidate_links_omitted'] = coverage['candidate_links_total'] - len(coverage['candidate_links'])
    # A textless PDF may still carry incorporated links or meaningful images.
    return ''.join(fragments), 'partial', coverage


def _retain_links(coverage, page, text, number, offset, source_url):
    try:
        for link in _page_links(page, text, number, offset, source_url, coverage['pdf_uri_base_requires_review']):
            coverage['candidate_links_total'] += 1
            if len(coverage['candidate_links']) < MAX_LINKS:
                coverage['candidate_links'].append({**link, 'anchor_index': coverage['candidate_links_total'],
                    'relation': 'candidate_incorporated_reference'})
    except Exception:
        coverage['page_spans'][-1]['annotation_scan_status'] = 'failed_requires_review'

"""PDF protocol/locator failures; no fabricated banking data or network fixtures."""
import hashlib
import io
import json

import pytest

pypdf = pytest.importorskip('pypdf')
from pypdf.generic import ArrayObject, DecodedStreamObject, DictionaryObject, NameObject, TextStringObject

from cdr_terms import pdf_extraction as pdf
from cdr_terms.extraction import extract_document
from cdr_terms.store import EvidenceStore


def protocol_pdf(texts, *, uri=None, indirect_uri=False, uri_base=None, encrypted=False):
    writer = pypdf.PdfWriter()
    for text in texts:
        page = writer.add_blank_page(width=200, height=200)
        font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
                                 NameObject('/Subtype'): NameObject('/Type1'),
                                 NameObject('/BaseFont'): NameObject('/Helvetica')})
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'):
            DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
        stream = DecodedStreamObject()
        literal = text.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
        stream.set_data(('BT /F1 10 Tf 10 100 Td (' + literal + ') Tj ET').encode('ascii'))
        page[NameObject('/Contents')] = writer._add_object(stream)
        if uri:
            action_type = NameObject('/URI')
            action_value = TextStringObject(uri)
            if indirect_uri:
                action_type = writer._add_object(action_type)
                action_value = writer._add_object(action_value)
            page[NameObject('/Annots')] = ArrayObject([writer._add_object(DictionaryObject({
                NameObject('/Type'): NameObject('/Annot'), NameObject('/Subtype'): NameObject('/Link'),
                NameObject('/A'): DictionaryObject({NameObject('/S'): action_type,
                                                   NameObject('/URI'): action_value})}))])
    if encrypted:
        writer.encrypt('protocol-only')
    if uri_base is not None:
        writer.root_object[NameObject('/URI')] = DictionaryObject({NameObject('/Base'): TextStringObject(uri_base)})
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def test_page_offsets_and_hashes_bind_exact_text_and_blank_review():
    body = protocol_pdf(['Protocol alpha.', '', 'Protocol gamma.'])
    text, status, coverage = extract_document(body, 'application/pdf', 'https://example.test/terms.pdf')
    assert status == 'partial' and coverage['pages'] == coverage['pages_processed'] == 3
    assert coverage['unreadable_pages'] == [2] and coverage['ocr_status'] == 'not_performed'
    assert coverage['table_structure_status'] == 'unreviewed'
    for span in coverage['page_spans']:
        value = text[span['start']:span['end']]
        assert hashlib.sha256(value.encode()).hexdigest() == span['text_sha256']
    assert text.count(pdf.SEPARATOR) == 2


def test_page_failure_preserves_later_text_and_marks_gap(monkeypatch):
    original, count = pdf._page_text, 0
    def read(page, maximum):
        nonlocal count
        count += 1
        if count == 2:
            raise ValueError('protocol corrupt middle page')
        return original(page, maximum)
    monkeypatch.setattr(pdf, '_page_text', read)
    text, status, coverage = pdf.extract_pdf(protocol_pdf(['Alpha.', 'Beta.', 'Gamma.']), 'https://example.test/')
    assert status == 'partial' and 'Alpha.' in text and 'Gamma.' in text and 'Beta.' not in text
    assert coverage['unreadable_pages'] == [2]
    assert coverage['page_spans'][1]['reason'] == 'page_extraction_failed'


def test_page_and_text_limits_leave_explicit_unprocessed_ranges(monkeypatch):
    monkeypatch.setattr(pdf, 'MAX_PAGES', 1)
    text, _, coverage = pdf.extract_pdf(protocol_pdf(['Alpha.', 'Beta.']), 'https://example.test/')
    assert 'Beta.' not in text and coverage['unprocessed_page_range'] == [2, 2]
    monkeypatch.setattr(pdf, 'MAX_PAGES', 512)
    monkeypatch.setattr(pdf, 'MAX_PAGE_CHARACTERS', 3)
    text, _, coverage = pdf.extract_pdf(protocol_pdf(['Alpha.', 'B.']), 'https://example.test/')
    assert 'Alpha.' not in text and 'B.' in text
    assert coverage['page_spans'][0]['reason'] == 'page_text_limit'


def test_pdf_candidates_keep_occurrences_and_never_execute_uri_actions(monkeypatch):
    body = protocol_pdf(['https://example.test/printed', 'Second.'], uri='/linked.pdf')
    monkeypatch.setattr(pdf, 'MAX_LINKS', 2)
    text, _, coverage = pdf.extract_pdf(body, 'https://example.test/start.pdf')
    assert coverage['candidate_links_total'] == 3 and coverage['candidate_links_omitted'] == 1
    first, second = coverage['candidate_links']
    assert text[first['text_start']:first['text_end']] == first['sourceUrl']
    assert second['url'] == 'https://example.test/linked.pdf' and second['page'] == 1
    assert first['relation'] == second['relation'] == 'candidate_incorporated_reference'


@pytest.mark.parametrize('scheme', ['HTTPS', 'Http', 'hTtPs'])
def test_printed_scheme_case_keeps_exact_source_and_normalized_fetch_url(scheme):
    printed = scheme + '://Example.Test/Terms.pdf?Section=Fees'
    text, status, coverage = pdf.extract_pdf(protocol_pdf(['First page.', 'Read ' + printed]), 'https://example.test/')
    assert status == 'partial' and coverage['candidate_links_total'] == 1
    link = coverage['candidate_links'][0]
    assert link['sourceUrl'] == link['href'] == printed
    assert link['url'] == scheme.lower() + '://example.test/Terms.pdf?Section=Fees'
    assert link['page'] == 2 and text[link['text_start']:link['text_end']] == printed


@pytest.mark.parametrize(('printed', 'expected'), [
    ('(https://example.test/terms)', 'https://example.test/terms'),
    ('[https://example.test/terms].', 'https://example.test/terms'),
    ('{https://example.test/terms};', 'https://example.test/terms'),
    ('([https://example.test/terms_(Fees)]).', 'https://example.test/terms_(Fees)'),
    ('https://example.test/terms_(Fees)', 'https://example.test/terms_(Fees)'),
    ('https://example.test/terms_(Nested_(Fees))', 'https://example.test/terms_(Nested_(Fees))'),
    ('https://example.test/terms_[Fees]', 'https://example.test/terms_[Fees]'),
    ('https://example.test/terms_{Fees}', 'https://example.test/terms_{Fees}'),
    ('https://example.test/terms_(Fees;)', 'https://example.test/terms_(Fees;)'),
    ('https://example.test/terms?range=[0,1]', 'https://example.test/terms?range=[0,1]'),
    ('(https://example.test/terms_%28Fees%29)', 'https://example.test/terms_%28Fees%29'),
    ('https://example.test/terms)(Fees)', 'https://example.test/terms)(Fees)'),
])
def test_printed_url_trims_only_trailing_unmatched_delimiters(printed, expected):
    text, status, coverage = pdf.extract_pdf(protocol_pdf(['Prefix.', 'Read ' + printed]), 'https://example.test/')
    assert status == 'partial' and coverage['candidate_links_total'] == 1
    link = coverage['candidate_links'][0]
    assert link['sourceUrl'] == link['href'] == expected
    assert link['url'] == expected
    assert link['page'] == 2 and text[link['text_start']:link['text_end']] == expected
    assert coverage['page_spans'][1]['start'] <= link['text_start'] < link['text_end'] <= coverage['page_spans'][1]['end']


def test_scanner_does_not_reassemble_broken_schemes_or_rewrite_annotation_uri():
    body = protocol_pdf(['HTTp:/ /example.test/wrapped'], uri='https://example.test/literal)')
    _, status, coverage = pdf.extract_pdf(body, 'https://example.test/')
    assert status == 'partial' and coverage['candidate_links_total'] == 1
    assert coverage['candidate_links'][0]['source_kind'] == 'pdf_uri_annotation_candidate'
    assert coverage['candidate_links'][0]['sourceUrl'] == 'https://example.test/literal)'
    assert coverage['policy_version'] == 'pdf-page-evidence-2'


def test_scanner_retains_unicode_whitespace_boundaries_and_exact_occurrences():
    text = '(HTTPS://example.test/one)\u00a0[hTtPs://example.test/two]. http\u017f://example.test/not-ascii'
    links = list(pdf._page_links({}, text, 3, 100, 'https://example.test/', False))
    assert len(links) == 2
    assert [link['sourceUrl'] for link in links] == ['HTTPS://example.test/one', 'hTtPs://example.test/two']
    for link in links:
        assert text[link['text_start']-100:link['text_end']-100] == link['sourceUrl']


def test_trimmed_case_insensitive_candidates_still_obey_retention_limit(monkeypatch):
    monkeypatch.setattr(pdf, 'MAX_LINKS', 2)
    body = protocol_pdf(['(HTTPS://example.test/one) [https://example.test/two] {hTtPs://example.test/three}'])
    text, status, coverage = pdf.extract_pdf(body, 'https://example.test/')
    assert status == 'partial'
    assert coverage['candidate_links_total'] == 3 and coverage['candidate_links_omitted'] == 1
    assert len(coverage['candidate_links']) == 2
    assert [link['anchor_index'] for link in coverage['candidate_links']] == [1, 2]
    for link in coverage['candidate_links']:
        assert text[link['text_start']:link['text_end']] == link['sourceUrl']


def test_delimiter_scan_preserves_inner_punctuation_with_long_trailing_suffix():
    value = 'https://example.test/terms_(Fees;)' + ')' * 10000 + '].;'
    assert pdf._printed_url(value) == 'https://example.test/terms_(Fees;)'


def test_encrypted_and_invalid_pdf_remain_failed():
    assert pdf.extract_pdf(protocol_pdf(['Private.'], encrypted=True), 'https://example.test/')[2]['reason'] == 'encrypted_pdf'
    assert pdf.extract_pdf(b'%PDF-broken', 'https://example.test/')[1] == 'failed'


def test_indirect_pdf_action_and_uri_are_resolved_without_losing_reference():
    direct = protocol_pdf(['Protocol.'], uri='https://example.test/linked.pdf')
    indirect = protocol_pdf(['Protocol.'], uri='https://example.test/linked.pdf', indirect_uri=True)
    first = pdf.extract_pdf(direct, 'https://example.test/')[2]
    second = pdf.extract_pdf(indirect, 'https://example.test/')[2]
    assert first['candidate_links_total'] == second['candidate_links_total'] == 1
    assert first['candidate_links'] == second['candidate_links']


def test_declared_pdf_uri_base_cannot_silently_fetch_wrong_relative_target():
    relative = protocol_pdf(['Protocol.'], uri='terms.pdf', uri_base='https://example.test/declared/')
    absolute = protocol_pdf(['Protocol.'], uri='https://example.test/exact.pdf', uri_base='https://example.test/declared/')
    coverage = pdf.extract_pdf(relative, 'https://example.test/acquired/start.pdf')[2]
    assert coverage['pdf_uri_base_requires_review'] is True
    assert coverage['candidate_links'][0]['url'] is None
    assert coverage['candidate_links'][0]['href'] == 'terms.pdf'
    assert coverage['candidate_links'][0]['source_kind'] == 'pdf_uri_base_requires_review'
    assert pdf.extract_pdf(absolute, 'https://example.test/acquired/start.pdf')[2]['candidate_links'][0]['url'] == 'https://example.test/exact.pdf'


def test_page_locator_cannot_point_at_another_page_or_separator(tmp_path):
    body = protocol_pdf(['Alpha.', 'Beta.'])
    text, status, coverage = pdf.extract_pdf(body, 'https://example.test/')
    with EvidenceStore(tmp_path / 'evidence') as store:
        document = store.register_document('https://example.test/terms.pdf')
        version = store.record_check(document_id=document, check_id=hashlib.sha256(body).hexdigest(), checked_at='2026-09-14T00:00:00Z',
                                     status='fetched', http_status=200, body=body, media_type='application/pdf')
        extraction = store.register_extraction(document_version_id=version, extractor_version='protocol',
                                               text=text, observed_at='2026-09-14T00:00:01Z', status=status, coverage=coverage)
        first, second = coverage['page_spans']
        clause = store.add_clause(extraction, start=first['start'], end=first['end'], page=1)
        assert json.loads(store.db.execute('SELECT locator_json FROM clauses WHERE clause_id=?', (clause,)).fetchone()[0])['page'] == 1
        for start, end, page in [(first['start'], first['end'], 2), (first['start'], second['end'], 1),
                                 (first['end'], second['start'], 1), (second['start'], second['end'], 999)]:
            with pytest.raises(ValueError, match='Page locator'):
                store.add_clause(extraction, start=start, end=end, page=page)

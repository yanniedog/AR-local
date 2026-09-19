"""Reject the CRLF-only input observed by the Sep 19 natural Pi run.

Fault injections use retained CDR provenance; no model or network is called.
"""
import pytest

from cdr_terms.extraction import extract_document
from cdr_terms.identity import canonical_json, digest
from cdr_terms.ingest import registry_context
from cdr_terms.queue import EmptyAnalysisText, TermsQueue
from cdr_terms.store import EvidenceStore
from tests.test_cdr_terms_evidence import evidence, NOW
from tests.test_pi_terms_worker import setup, invoke, simulate


CAPTURED_EMPTY = '\r\n' * 6


@pytest.mark.parametrize('text', ['', CAPTURED_EMPTY, '\t \n\u00a0\u2003'])
def test_plain_empty_preserves_text_but_fails_extraction(text):
    actual, status, coverage = extract_document(text.encode(), 'text/plain', 'https://example.test/')
    assert actual == text and status == 'failed'
    assert coverage == {'characters': len(text), 'reason': 'empty_extracted_text'}


def test_empty_html_retains_link_candidates():
    text, status, coverage = extract_document(
        b'<p>\r\n</p><a href="terms.pdf"></a><script>hidden</script>',
        'text/html', 'https://example.test/')
    assert text == '\n\r\n\n' and status == 'failed'
    assert coverage['reason'] == 'empty_extracted_text'
    assert coverage['candidate_links'][0]['url'] == 'https://example.test/terms.pdf'


def test_short_nonempty_text_and_offsets_are_preserved():
    text = '\r\n0\t'
    actual, status, _ = extract_document(text.encode(), 'text/plain', 'https://example.test/')
    assert (actual, status) == (text, 'complete')


@pytest.mark.parametrize('text', ['', CAPTURED_EMPTY, '\u00a0\n\f\n'])
def test_enqueue_rejects_empty_legacy_extraction_without_job(evidence, text):
    store, _, key, _, version, *_ = evidence
    status = 'complete' if text else 'partial'
    extraction = store.register_extraction(document_version_id=version, extractor_version='document-text-3',
        text=text, observed_at=NOW, status=status, coverage={'characters': len(text)})
    with pytest.raises(EmptyAnalysisText, match='empty_extracted_text'):
        TermsQueue(store).enqueue(extraction, {**registry_context(), 'product_keys': [key]})
    assert store.db.execute('SELECT COUNT(*) FROM analysis_jobs').fetchone()[0] == 0
    row = store.db.execute('SELECT * FROM extractions WHERE extraction_id=?', (extraction,)).fetchone()
    assert row['status'] == status  # Legacy evidence is immutable.
    assert store.read_blob(row['text_sha256']).decode() == text


def legacy_empty_job(setup):
    with EvidenceStore(setup[0]) as store:
        old = store.db.execute('SELECT x.* FROM analysis_jobs j JOIN extractions x USING(extraction_id) '
                               'WHERE job_id=?', (setup[3],)).fetchone()
        extraction = store.register_extraction(document_version_id=old['document_version_id'],
            extractor_version='document-text-3', text=CAPTURED_EMPTY, observed_at=NOW,
            status='complete', coverage={'characters': 12})
        context = TermsQueue(store).validate_input(setup[3])
        sha = digest(context); job = digest([extraction, sha])
        blob = store.put_blob(canonical_json(context).encode())
        # Reproduce an already-queued pre-fix row, not new public admission.
        with store.db:
            store.db.execute('INSERT INTO analysis_jobs VALUES (?,?,?,?,?,?)', (job, extraction, sha, blob, 0, NOW))
            queue = TermsQueue(store)
            queue._event(job, 'queued', NOW, None, None, None)
            queue._prioritize(job, 0, NOW)
        return job, dict(store.db.execute('SELECT * FROM extractions WHERE extraction_id=?', (extraction,)).fetchone())


@pytest.mark.parametrize('valid_next', [False, True])
def test_worker_blocks_legacy_empty_before_model_and_continues(setup, monkeypatch, valid_next):
    job, original = legacy_empty_job(setup)
    if not valid_next:
        with EvidenceStore(setup[0]) as store:
            TermsQueue(store).event(setup[3], 'superseded', now=NOW)
    calls = simulate(monkeypatch, setup)
    result = invoke(setup)
    assert result['result'] == ('STAGED' if valid_next else 'NO_WORK')
    assert len(calls) == int(valid_next)
    with EvidenceStore(setup[0]) as store:
        events = store.db.execute('SELECT status,error_code FROM job_events WHERE job_id=? ORDER BY sequence', (job,)).fetchall()
        assert [tuple(e) for e in events] == [('queued', None), ('blocked', 'empty_extracted_text')]
        assert dict(store.db.execute('SELECT * FROM extractions WHERE extraction_id=?', (original['extraction_id'],)).fetchone()) == original
        assert store.read_blob(original['text_sha256']).decode() == CAPTURED_EMPTY

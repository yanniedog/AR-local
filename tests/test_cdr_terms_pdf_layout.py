"""Geometry protocol fixtures are not bank/product acceptance evidence."""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path

import pytest

from cdr_terms.identity import digest
from cdr_terms.pdf_layout import build_pdf_layout
from cdr_terms.pdf_layout_contract import LayoutLimits, RetainedExtraction


def protocol_pdf(content=b'BT /F1 10 Tf 10 40 Td (protocol) Tj ET', *, pages=1, encrypted=False,
                 rotation=0, user_unit=1, crop=None):
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject, FloatObject, NumberObject, RectangleObject
    writer = PdfWriter()
    font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
                             NameObject('/Subtype'): NameObject('/Type1'),
                             NameObject('/BaseFont'): NameObject('/Helvetica')})
    for _ in range(pages):
        page = writer.add_blank_page(200, 200)
        page[NameObject('/Rotate')] = NumberObject(rotation)
        page[NameObject('/UserUnit')] = FloatObject(user_unit)
        if crop is not None:
            page[NameObject('/CropBox')] = RectangleObject(crop)
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): font})})
        stream = DecodedStreamObject()
        stream.set_data(content)
        page[NameObject('/Contents')] = writer._add_object(stream)
    if encrypted:
        writer.encrypt('protocol password')
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def binding(body, *, text=None, coverage=None):
    from cdr_terms.pdf_extraction import extract_pdf
    if coverage is None:
        text, status, coverage = extract_pdf(body, 'https://example.org/protocol.pdf')
    else:
        status = 'partial'
    document_id = digest({'source_url': 'https://example.org/protocol.pdf'})
    body_sha = hashlib.sha256(body).hexdigest()
    version_id = digest([document_id, body_sha])
    text_sha = hashlib.sha256(text.encode()).hexdigest()
    extraction_id = digest([version_id, 'document-text-3', text_sha, status, coverage])
    return RetainedExtraction(document_id=document_id, document_version_id=version_id,
                             source_sha256=body_sha, extraction_id=extraction_id,
                             extractor_version='document-text-3', text=text,
                             text_sha256=text_sha, status=status, coverage=coverage)


def build(tmp_path, body=None, **kwargs):
    body = body or protocol_pdf()
    retained = binding(body)
    manifest = build_pdf_layout(body, retained=retained, output_dir=tmp_path / 'sidecar', **kwargs)
    pages = [json.loads((tmp_path / 'sidecar' / row['file']).read_bytes()) for row in manifest['pages']]
    return manifest, pages


def test_real_parser_callback_evidence_stays_partial(tmp_path):
    manifest, pages = build(tmp_path)
    assert manifest['status'] == 'partial'
    assert manifest['alignment_status'] == 'alignment_unverified'
    assert manifest['table_structure_status'] == 'unreviewed'
    assert manifest['footnote_associations_status'] == 'unreviewed'
    assert manifest['ocr_status'] == 'not_performed'
    assert pages[0]['runs']
    assert any(run['text'] == 'protocol' for run in pages[0]['runs'])
    assert all(run['source_text_span'] is None for run in pages[0]['runs'])
    assert all(isinstance(value, str) for run in pages[0]['runs'] for value in run['cm'])
    assert os.path.samefile(tmp_path / 'sidecar/manifest.json', tmp_path / 'sidecar/manifest.pending.json')


def test_repeated_text_and_empty_callbacks_are_retained(tmp_path):
    _, pages = build(tmp_path, protocol_pdf(b'BT /F1 10 Tf 10 40 Td (repeat) Tj 0 -12 Td (repeat) Tj ET'))
    runs = pages[0]['runs']
    assert any(run['text'] == '' for run in runs)
    assert ''.join(run['text'] for run in runs).count('repeat') == 2
    assert [run['callback_ordinal'] for run in runs] == list(range(1, len(runs) + 1))


def test_parent_mismatch_refused_before_output(tmp_path):
    body = protocol_pdf()
    retained = binding(body)
    with pytest.raises(ValueError, match='source_sha256'):
        build_pdf_layout(body + b'changed', retained=retained, output_dir=tmp_path / 'out')
    assert not (tmp_path / 'out').exists()


def test_selected_pages_and_unprocessed_ranges_are_explicit(tmp_path):
    manifest, pages = build(tmp_path, protocol_pdf(pages=4), page_numbers=[2, 4])
    assert [page['page'] for page in pages] == [2, 4]
    assert manifest['unprocessed_page_ranges'] == [[1, 1], [3, 3]]
    assert manifest['remaining_callback_count'] is None


def test_textless_page_never_means_blank_or_complete(tmp_path):
    _, pages = build(tmp_path, protocol_pdf(b'0 0 10 10 re f'))
    assert pages[0]['status'] == 'textless_nontext_review_required'
    assert pages[0]['primitives']
    assert pages[0]['table_candidates'] == []
    assert pages[0]['footnote_candidates'] == []
    assert pages[0]['text_status'] == 'no_text_observed_requires_review'


def test_callback_cap_is_explicit_and_retains_sibling(tmp_path):
    manifest, pages = build(tmp_path, protocol_pdf(pages=2), limits=LayoutLimits(callbacks_per_page=1))
    assert len(pages) == 2
    assert all('callback_limit' in page['reasons'] for page in pages)
    assert all(page['remaining_callback_count'] is None for page in pages)
    assert manifest['status'] == 'partial'


def test_final_fsync_failure_never_exposes_manifest(tmp_path, monkeypatch):
    import cdr_terms.pdf_layout_contract as contract
    original = contract.write_exclusive
    real_sync = contract.os.fsync
    at_manifest = False
    def write(path, body, budget):
        nonlocal at_manifest
        at_manifest = path.name == 'manifest.pending.json'
        try:
            return original(path, body, budget)
        finally:
            at_manifest = False
    def fsync(fd):
        if at_manifest:
            raise OSError('protocol final fsync failed')
        real_sync(fd)
    monkeypatch.setattr(contract, 'write_exclusive', write)
    monkeypatch.setattr(contract.os, 'fsync', fsync)
    with pytest.raises(OSError, match='final fsync failed'):
        build(tmp_path)
    assert not (tmp_path / 'sidecar/manifest.json').exists()
    assert (tmp_path / 'sidecar/manifest.pending.json').exists()


def test_output_collision_preserves_unknown_files(tmp_path):
    (tmp_path / 'sidecar').mkdir()
    (tmp_path / 'sidecar/unknown').write_bytes(b'preserve')
    with pytest.raises(FileExistsError):
        build(tmp_path)
    assert (tmp_path / 'sidecar/unknown').read_bytes() == b'preserve'


def test_schema_accepts_only_unreviewed_page_and_manifest(tmp_path):
    from jsonschema import Draft202012Validator
    schema = json.loads((Path(__file__).parents[1] / 'contracts/product_terms/pdf-layout-candidates-v1.schema.json').read_bytes())
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    manifest, pages = build(tmp_path)
    for record in [manifest, *pages]:
        validator.validate(record)
    for bad in [{**manifest, 'status': 'complete'}, {**manifest, 'legal_effective_date': '2026-01-01'},
                {**pages[0], 'alignment_status': 'verified'}]:
        assert not validator.is_valid(bad)


@pytest.mark.parametrize('field', ['source_sha256', 'text_sha256', 'document_version_id', 'extraction_id'])
def test_forged_parent_identity_refused(tmp_path, field):
    from dataclasses import replace
    body = protocol_pdf()
    retained = replace(binding(body), **{field: '0' * 64})
    with pytest.raises(ValueError):
        build_pdf_layout(body, retained=retained, output_dir=tmp_path / 'sidecar')
    assert not (tmp_path / 'sidecar').exists()


@pytest.mark.parametrize('fault', ['bool_start', 'bad_page', 'bad_hash', 'bad_separator', 'trailing_text'])
def test_rehashed_but_invalid_span_contract_refused(tmp_path, fault):
    body = protocol_pdf(pages=2)
    retained = binding(body)
    text, coverage = retained.text, json.loads(json.dumps(retained.coverage))
    if fault == 'bool_start':
        coverage['page_spans'][0]['start'] = False
    elif fault == 'bad_page':
        coverage['page_spans'][0]['page'] = 2
    elif fault == 'bad_hash':
        coverage['page_spans'][0]['text_sha256'] = '0' * 64
    elif fault == 'bad_separator':
        text = text.replace('\n\f\n', '\n!\n')
    else:
        text += 'unbound'
    retained = binding(body, text=text, coverage=coverage)
    with pytest.raises(ValueError):
        build_pdf_layout(body, retained=retained, output_dir=tmp_path / 'sidecar')
    assert not (tmp_path / 'sidecar').exists()


@pytest.mark.parametrize('name,value', [('seconds',106),('pages',513),('callbacks_total',True),('output_bytes',0)])
def test_limits_can_only_be_lowered(name, value):
    from cdr_terms.pdf_layout_contract import Budget
    with pytest.raises(ValueError, match='invalid_or_increased_limit'):
        Budget(LayoutLimits(**{name:value}))


@pytest.mark.parametrize('value', [float('nan'),float('inf'),True,'1',10**102])
def test_nonfinite_non_numeric_or_unbounded_geometry_refused(value):
    from cdr_terms.pdf_layout_contract import decimal_observation
    with pytest.raises(ValueError, match='invalid_geometry'):
        decimal_observation(value)


def test_geometry_is_parsed_numeric_observation_not_binary_money():
    from decimal import Decimal
    from cdr_terms.pdf_layout_contract import decimal_observation
    assert decimal_observation(0.1) == '0.1'
    assert decimal_observation(Decimal('1.2300')) == '1.2300'
    assert decimal_observation(-0.0) == '-0.0'


def collector(limits=None):
    from cdr_terms.pdf_layout import PageCollector
    from cdr_terms.pdf_layout_contract import Budget
    return PageCollector(1, None, Budget(limits or LayoutLimits()))


IDENTITY = [1,0,0,1,0,0]


def test_identical_raw_callbacks_stay_separate_and_invalid_matrix_is_explicit():
    c = collector()
    c.visit_text('same',IDENTITY,IDENTITY,None,1)
    c.visit_text('same',IDENTITY,IDENTITY,None,1)
    c.visit_text('bad',[float('nan')]*6,IDENTITY,None,1)
    page = c.finish()
    assert [run['callback_ordinal'] for run in page['runs']] == [1,2,3]
    assert page['runs'][0]['text_sha256'] == page['runs'][1]['text_sha256']
    assert page['runs'][2]['text'] == 'bad'
    assert page['runs'][2]['coordinate_status'] == 'invalid_geometry'
    assert page['runs'][2]['source_text_span'] is None
    assert page['runs'][2]['tm'] == ['1','0','0','1','0','0']


def test_invalid_font_size_does_not_discard_valid_raw_matrices():
    c=collector()
    c.visit_text('text',IDENTITY,IDENTITY,None,float('nan'))
    run=c.finish()['runs'][0]
    assert run['font_size'] is None
    assert run['cm']==run['tm']==['1','0','0','1','0','0']


def test_bad_crop_does_not_discard_valid_page_box_and_rotation():
    class Page:
        mediabox=[0,0,200,200]
        cropbox=[0,float('nan'),200,200]
        def get(self,key,default):return default
    c=collector()
    c.geometry(Page())
    page=c.finish()
    assert page['media_box']==['0','0','200','200']
    assert page['crop_box'] is None
    assert page['rotation']=='0' and page['user_unit']=='1'


def test_large_callback_is_omitted_without_silent_text_truncation():
    c = collector(LayoutLimits(characters_per_callback=3))
    c.visit_text('four',IDENTITY,IDENTITY,None,1)
    c.visit_text('ok',IDENTITY,IDENTITY,None,1)
    page=c.finish()
    assert [run['text'] for run in page['runs']] == ['ok']
    assert page['runs'][0]['callback_ordinal'] == 2
    assert page['omissions'] == [{'callback_ordinal':1,'characters':4,'reason':'characters_per_callback_limit'}]
    assert 'oversized_callback_omitted' in page['reasons']
    assert page['text_status'] == 'text_observation_incomplete'


def test_vector_form_clipping_and_non_geometry_counts_are_explicit():
    c=collector()
    for op,args in [(b'BT',[]),(b'Do',['/PrivateNameNotSerialized']),(b'W',[]),(b'c',[0,0,1,1,2,2])]:
        c.visit_operator(op,args,IDENTITY,IDENTITY)
    page=c.finish()
    assert page['unsupported_operators']==['Do','W','c']
    assert page['observed_counts']['unretained_operator_callbacks']==1
    assert 'PrivateName' not in json.dumps(page)


def test_font_size_alone_is_never_a_footnote_and_regions_are_candidates():
    c=collector()
    c.visit_text('small footer',IDENTITY,IDENTITY,None,0.1)
    assert c.page['footnote_candidates']==[]
    c.visit_text('* possible marker',IDENTITY,IDENTITY,None,10)
    for _ in range(4):
        c.visit_operator(b'l',[10,20],IDENTITY,IDENTITY)
    page=c.finish()
    assert len(page['footnote_candidates'])==len(page['table_candidates'])==1
    assert all(region['association'] is None for field in ('footnote_candidates','table_candidates') for region in page[field])
    assert page['footnote_candidates'][0]['evidence_ids']==['p1:t2']


def test_region_cap_records_unreviewed_omission():
    c=collector(LayoutLimits(regions_per_page=1))
    for _ in range(3):
        c.visit_text('* candidate',IDENTITY,IDENTITY,None,10)
    page=c.finish()
    assert len(page['footnote_candidates'])==1
    assert 'region_limit' in page['reasons']
    assert page['region_candidates_omitted'] == 2


def test_page_byte_cap_stops_before_append():
    from cdr_terms.pdf_layout import PageStop
    c=collector(LayoutLimits(page_json_bytes=16*1024))
    with pytest.raises(PageStop,match='page_output_limit'):
        c.visit_text('bounded',IDENTITY,IDENTITY,None,10)
    assert c.page['runs']==[]


def test_operator_cap_and_document_callback_cap(tmp_path):
    from cdr_terms.pdf_layout import PageStop
    c=collector(LayoutLimits(operators_per_page=1))
    c.visit_operator(b'BT',[],IDENTITY,IDENTITY)
    with pytest.raises(PageStop,match='operation_limit'):
        c.visit_operator(b'ET',[],IDENTITY,IDENTITY)
    manifest,pages=build(tmp_path,protocol_pdf(pages=3),limits=LayoutLimits(callbacks_total=1))
    assert len(pages)==1
    assert manifest['unprocessed_page_ranges']==[[2,3]]
    assert 'document_limit' in manifest['reasons']


def test_one_corrupt_page_retains_sibling_and_marks_unknown_count(tmp_path,monkeypatch):
    import pypdf
    original=pypdf.PageObject.extract_text
    calls=0
    body=protocol_pdf(pages=2)
    retained=binding(body)
    def fail_one(self,*args,**kwargs):
        nonlocal calls
        calls+=1
        if calls==1:raise ValueError('protocol bad page')
        return original(self,*args,**kwargs)
    monkeypatch.setattr(pypdf.PageObject,'extract_text',fail_one)
    manifest=build_pdf_layout(body,retained=retained,output_dir=tmp_path/'sidecar')
    pages=[json.loads((tmp_path/'sidecar'/p['file']).read_bytes()) for p in manifest['pages']]
    assert len(pages)==2
    assert 'page_parser_failed' in pages[0]['reasons']
    assert pages[0]['remaining_callback_count'] is None
    assert any(r['text']=='protocol' for r in pages[1]['runs'])


@pytest.mark.parametrize('kind',['encrypted','corrupt','parser_version','parser_unavailable'])
def test_unavailable_sources_never_claim_usable_geometry(tmp_path,monkeypatch,kind):
    import builtins
    import pypdf
    body=protocol_pdf(encrypted=kind=='encrypted') if kind!='corrupt' else b'%PDF-invalid'
    retained=binding(body)
    if kind=='parser_version':monkeypatch.setattr(pypdf,'__version__','unreviewed')
    if kind=='parser_unavailable':
        real_import=builtins.__import__
        def unavailable(name,*args,**kwargs):
            if name=='pypdf':raise ImportError('protocol unavailable')
            return real_import(name,*args,**kwargs)
        monkeypatch.setattr(builtins,'__import__',unavailable)
    result=build_pdf_layout(body,retained=retained,output_dir=tmp_path/'sidecar')
    assert result['status']=='partial'
    assert result['pages']==[] and result['pages_total'] is None
    assert result['remaining_callback_count'] is None
    assert result['reasons']==[{'corrupt':'parser_failed','parser_version':'parser_version_unreviewed'}.get(kind,kind)]


def test_page_cap_and_huge_unprocessed_range_are_bounded(tmp_path):
    from cdr_terms.pdf_layout import _unprocessed_ranges
    assert _unprocessed_ranges(10**12,{1,3})==[[2,2],[4,10**12]]
    manifest,pages=build(tmp_path,protocol_pdf(pages=3),limits=LayoutLimits(pages=1))
    assert len(pages)==1
    assert manifest['unprocessed_page_ranges']==[[2,3]]
    assert 'page_limit' in manifest['reasons']


def test_parser_callbacks_obey_shared_deadline(tmp_path,monkeypatch):
    import pypdf
    body=protocol_pdf()
    retained=binding(body)
    now=[0]
    def stall(self,**kwargs):
        now[0]=106
        kwargs['visitor_text']('too late',IDENTITY,IDENTITY,None,1)
    monkeypatch.setattr(pypdf.PageObject,'extract_text',stall)
    with pytest.raises(ValueError,match='shared_deadline'):
        build_pdf_layout(body,retained=retained,output_dir=tmp_path/'sidecar',clock=lambda:now[0])
    assert not (tmp_path/'sidecar/manifest.json').exists()


def test_final_fsync_deadline_crossing_never_exposes_manifest(tmp_path,monkeypatch):
    import cdr_terms.pdf_layout_contract as contract
    real_write,real_sync=contract.write_exclusive,contract.os.fsync
    now=[0]
    at_manifest=False
    def write(path,body,budget):
        nonlocal at_manifest
        at_manifest=path.name=='manifest.pending.json'
        try:return real_write(path,body,budget)
        finally:at_manifest=False
    def sync(fd):
        real_sync(fd)
        if at_manifest:now[0]=106
    monkeypatch.setattr(contract,'write_exclusive',write)
    monkeypatch.setattr(contract.os,'fsync',sync)
    with pytest.raises(ValueError,match='shared_deadline'):
        build(tmp_path,clock=lambda:now[0])
    assert not (tmp_path/'sidecar/manifest.json').exists()
    assert (tmp_path/'sidecar/manifest.pending.json').exists()


@pytest.mark.parametrize('which',['page','manifest'])
def test_same_byte_replacement_refused_and_preserved(tmp_path,monkeypatch,which):
    import cdr_terms.pdf_layout_contract as contract
    real_write=contract.write_exclusive
    def replace_after_write(path,body,budget):
        identity=real_write(path,body,budget)
        if path.name==('page-0001.json' if which=='page' else 'manifest.pending.json'):
            path.rename(path.with_suffix('.original'))
            path.write_bytes(body)
        return identity
    monkeypatch.setattr(contract,'write_exclusive',replace_after_write)
    with pytest.raises(ValueError,match='output_identity_changed'):
        build(tmp_path)
    assert not (tmp_path/'sidecar/manifest.json').exists()
    assert list((tmp_path/'sidecar').glob('*.original'))


def test_earlier_page_replaced_during_later_write_refuses_manifest(tmp_path,monkeypatch):
    import cdr_terms.pdf_layout_contract as contract
    real_write=contract.write_exclusive
    def replace_prior(path,body,budget):
        identity=real_write(path,body,budget)
        if path.name=='page-0002.json':
            first=path.with_name('page-0001.json')
            saved=first.read_bytes()
            first.rename(path.with_name('preserved-first.json'))
            first.write_bytes(saved)
        return identity
    monkeypatch.setattr(contract,'write_exclusive',replace_prior)
    with pytest.raises(ValueError,match='output_identity_changed'):
        build(tmp_path,protocol_pdf(pages=2))
    assert not (tmp_path/'sidecar/manifest.json').exists()
    assert (tmp_path/'sidecar/preserved-first.json').exists()


def test_failed_final_link_preserves_pending_without_seal(tmp_path,monkeypatch):
    import cdr_terms.pdf_layout_contract as contract
    def fail(*args,**kwargs):raise OSError('protocol link failure')
    monkeypatch.setattr(contract.os,'link',fail)
    with pytest.raises(OSError,match='link failure'):
        build(tmp_path)
    assert not (tmp_path/'sidecar/manifest.json').exists()
    assert (tmp_path/'sidecar/manifest.pending.json').exists()


def test_real_parser_rotation_crop_user_unit_are_retained_without_alignment(tmp_path):
    _,pages=build(tmp_path,protocol_pdf(rotation=90,user_unit=2,crop=[10,20,180,190]))
    page=pages[0]
    assert page['media_box']==['0.0','0.0','200','200']
    assert page['crop_box']==['10','20','180','190']
    assert page['rotation']=='90' and page['user_unit']=='2'
    assert page['coordinate_status']=='parser_coordinates_unverified'
    assert all(run['source_text_span'] is None for run in page['runs'])


def test_nontext_form_or_curve_page_keeps_explicit_text_visibility():
    c=collector()
    c.visit_operator(b'c',[0,0,1,1,2,2],IDENTITY,IDENTITY)
    page=c.finish()
    assert page['status']=='partial'
    assert page['text_status']=='no_text_observed_requires_review'


@pytest.mark.parametrize('selected',[[True],[0],[2],[1,1],[],[1,0]])
def test_selection_validation_and_empty_selection(tmp_path,selected):
    if selected==[]:
        manifest,_=build(tmp_path,page_numbers=selected)
        assert manifest['unprocessed_page_ranges']==[[1,1]]
    else:
        with pytest.raises(ValueError,match='invalid_selected_pages'):
            build(tmp_path,page_numbers=selected)
        assert not (tmp_path/'sidecar').exists()


def test_input_cap_checked_before_parser_and_output(tmp_path,monkeypatch):
    import cdr_terms.pdf_layout as layout
    body=protocol_pdf()
    retained=binding(body)
    monkeypatch.setattr(layout,'_reader',lambda *_:pytest.fail('oversized input reached parser'))
    with pytest.raises(ValueError,match='pdf_input_byte_limit'):
        build_pdf_layout(body,retained=retained,output_dir=tmp_path/'sidecar',limits=LayoutLimits(input_bytes=1))
    assert not (tmp_path/'sidecar').exists()


def test_output_budget_cannot_expose_oversized_manifest(tmp_path):
    with pytest.raises(ValueError,match='json_byte_limit|output_limit'):
        build(tmp_path,limits=LayoutLimits(output_bytes=512))
    assert not (tmp_path/'sidecar/manifest.json').exists()


@pytest.mark.parametrize('which',['manifest.json','manifest.pending.json'])
def test_manifest_collision_preserves_unknown_path(tmp_path,monkeypatch,which):
    import cdr_terms.pdf_layout_contract as contract
    original=contract.seal_manifest
    def collide(path,body,budget):
        (path.parent/which).write_bytes(b'unknown prior output')
        return original(path,body,budget)
    monkeypatch.setattr(contract,'seal_manifest',collide)
    with pytest.raises(FileExistsError):
        build(tmp_path)
    assert (tmp_path/'sidecar'/which).read_bytes()==b'unknown prior output'


def test_short_write_never_seals(tmp_path,monkeypatch):
    import cdr_terms.pdf_layout_contract as contract
    original=Path.open
    class ShortWriter:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def write(self,body):return len(body)-1
    def short(path,mode='r',*args,**kwargs):
        return ShortWriter() if mode=='xb' else original(path,mode,*args,**kwargs)
    monkeypatch.setattr(Path,'open',short)
    with pytest.raises(OSError,match='short_output_write'):
        build(tmp_path)
    assert not (tmp_path/'sidecar/manifest.json').exists()


def test_parent_metadata_changed_mid_build_refuses_manifest(tmp_path,monkeypatch):
    import cdr_terms.pdf_layout_contract as contract
    body=protocol_pdf()
    retained=binding(body)
    original=contract.write_exclusive
    def mutate(path,payload,budget):
        identity=original(path,payload,budget)
        if path.name=='page-0001.json':retained.coverage['new_unknown_metadata']=True
        return identity
    monkeypatch.setattr(contract,'write_exclusive',mutate)
    with pytest.raises(ValueError,match='extraction_identity_mismatch'):
        build_pdf_layout(body,retained=retained,output_dir=tmp_path/'sidecar')
    assert not (tmp_path/'sidecar/manifest.json').exists()


def test_real_form_callbacks_preserve_duplicates_and_unverified_alignment(tmp_path):
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject, RectangleObject
    writer=PdfWriter()
    page=writer.add_page(PdfReader(io.BytesIO(protocol_pdf())).pages[0])
    form=DecodedStreamObject()
    form.set_data(b'BT /F1 10 Tf 10 40 Td (form text) Tj ET')
    form.update({NameObject('/Type'):NameObject('/XObject'),NameObject('/Subtype'):NameObject('/Form'),
                 NameObject('/BBox'):RectangleObject([0,0,200,200]),
                 NameObject('/Resources'):page['/Resources']})
    page['/Resources'][NameObject('/XObject')]=DictionaryObject({NameObject('/F0'):writer._add_object(form)})
    content=DecodedStreamObject();content.set_data(b'q /F0 Do Q q 1 0 0 1 0 80 cm /F0 Do Q')
    page[NameObject('/Contents')]=writer._add_object(content)
    out=io.BytesIO();writer.write(out)
    body=out.getvalue()
    original_runs=[]
    PdfReader(io.BytesIO(body)).pages[0].extract_text(visitor_text=lambda text,*args:original_runs.append(text))
    _,pages=build(tmp_path,body)
    assert [run['text'] for run in pages[0]['runs']]==original_runs
    assert sum('form text' in text for text in original_runs)>2
    assert 'Do' in pages[0]['unsupported_operators']
    assert all(run['source_text_span'] is None for run in pages[0]['runs'])


def test_independent_callback_character_caps_are_visible():
    from cdr_terms.pdf_layout import PageStop
    for limits,reason in [(LayoutLimits(page_characters=3),'page_character_limit'),
                          (LayoutLimits(total_characters=3),'document_character_limit')]:
        c=collector(limits)
        with pytest.raises(PageStop,match=reason):c.visit_text('four',IDENTITY,IDENTITY,None,1)
        page=c.finish()
        assert page['runs']==[] and page['remaining_callback_count'] is None
        assert page['text_status']=='text_observation_incomplete'


def test_document_operator_and_region_caps_are_visible():
    from cdr_terms.pdf_layout import PageStop
    c=collector(LayoutLimits(operators_total=1))
    c.visit_operator(b'BT',[],IDENTITY,IDENTITY)
    with pytest.raises(PageStop,match='document_operation_limit'):
        c.visit_operator(b'ET',[],IDENTITY,IDENTITY)
    c=collector(LayoutLimits(regions_total=1))
    c.visit_text('* first',IDENTITY,IDENTITY,None,1)
    c.visit_text('* second',IDENTITY,IDENTITY,None,1)
    page=c.finish()
    assert len(page['footnote_candidates'])==1 and page['region_candidates_omitted']==1


def test_external_parent_reparse_or_symlink_boundary_refused(tmp_path,monkeypatch):
    from types import SimpleNamespace
    import cdr_terms.pdf_layout_contract as contract
    original=Path.lstat
    def marked(path,*args,**kwargs):
        if path==tmp_path:
            value=original(path)
            return SimpleNamespace(st_mode=value.st_mode,st_file_attributes=0x400)
        return original(path,*args,**kwargs)
    monkeypatch.setattr(Path,'lstat',marked)
    with pytest.raises(ValueError,match='reparse'):
        contract.create_output(tmp_path/'sidecar',contract.Budget(LayoutLimits()))
    assert not (tmp_path/'sidecar').exists()

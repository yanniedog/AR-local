"""Private parser geometry candidates; never canonical text or legal authority."""
from __future__ import annotations

import io
from pathlib import Path

from . import pdf_layout_contract as contract
from .pdf_layout_contract import Budget, LayoutInterrupted, LayoutLimits, RetainedExtraction

OPERANDS = {'m': 2, 'l': 2, 're': 4, 'c': 6, 'v': 4, 'y': 4, 'cm': 6}
UNSUPPORTED = {'Do', 'W', 'W*', 'c', 'v', 'y', 'gs', 'sh', 'INLINE IMAGE'}
KNOWN = set(OPERANDS) | UNSUPPORTED | {'q', 'Q', 'h', 'S', 's', 'f', 'F', 'f*', 'B', 'B*', 'b', 'b*', 'n'}


class PageStop(Exception):
    pass


def _unprocessed_ranges(count, processed):
    # O(processed pages), including when the parser reports more than the cap.
    result, start = [], 1
    for number in sorted(processed):
        if start < number:
            result.append([start, number - 1])
        start = number + 1
    if start <= count:
        result.append([start, count])
    return result


class PageCollector:
    def __init__(self, number, span, budget):
        self.budget, self.limits = budget, budget.limits
        self.event = self.callbacks = self.operators = self.characters = self.unretained_operators = 0
        self.bytes = 0
        self.regions_omitted = 0
        self.stopped = False
        self.page = {'schema_version': 1, 'kind': 'pdf_layout_page', 'page': number,
                     'retained_page_text_sha256': span['text_sha256'] if span else None,
                     'retained_page_span': dict(span) if span else None,
                     'status': 'available_unreviewed', 'reasons': [], 'media_box': None,
                     'crop_box': None, 'rotation': None, 'user_unit': None,
                     'coordinate_status': 'parser_coordinates_unverified', 'printed_page_label': None,
                     'runs': [], 'primitives': [], 'omissions': [], 'unsupported_operators': [],
                     'table_candidates': [], 'footnote_candidates': [],
                     'alignment_status': 'alignment_unverified', 'remaining_callback_count': 0}

    def reason(self, value):
        if value not in self.page['reasons']:
            self.page['reasons'].append(value)

    def stop(self, reason):
        self.reason(reason)
        self.stopped = True
        raise PageStop(reason)

    def append(self, field, value):
        self.budget.check()
        # Reserve 16 KiB for page-level status, geometry and bounded counters.
        try:
            body = contract.encode(value, self.limits.page_json_bytes)
        except ValueError:
            self.stop('page_output_limit')
        if self.bytes + len(body) + 16 * 1024 > self.limits.page_json_bytes:
            self.stop('page_output_limit')
        self.bytes += len(body) + 1
        self.page[field].append(value)

    def geometry(self, page):
        for field, getter, length in [('media_box', lambda: list(page.mediabox), 4),
                                      ('crop_box', lambda: list(page.cropbox), 4),
                                      ('rotation', lambda: page.get('/Rotate', 0), None),
                                      ('user_unit', lambda: page.get('/UserUnit', 1), None)]:
            try:
                value = getter()
                self.page[field] = contract.numbers(value, length) if length else contract.decimal_observation(value)
            except Exception:
                self.reason('invalid_geometry')

    def numeric_field(self, target, field, value, length=None):
        try:
            target[field] = contract.numbers(value, length) if length else contract.decimal_observation(value)
        except Exception:
            target['coordinate_status'] = 'invalid_geometry'
            self.reason('invalid_geometry')

    def visit_text(self, text, cm, tm, font, font_size):
        self.budget.check()
        self.event += 1
        self.callbacks += 1
        self.budget.counts['callbacks'] += 1
        if self.callbacks > self.limits.callbacks_per_page:
            self.stop('callback_limit')
        if self.budget.counts['callbacks'] > self.limits.callbacks_total:
            self.stop('document_callback_limit')
        if not isinstance(text, str):
            self.stop('unsupported_callback_text')
        self.characters += len(text)
        self.budget.counts['characters'] += len(text)
        if self.characters > self.limits.page_characters:
            self.stop('page_character_limit')
        if self.budget.counts['characters'] > self.limits.total_characters:
            self.stop('document_character_limit')
        if len(text) > self.limits.characters_per_callback:
            self.reason('oversized_callback_omitted')
            self.append('omissions', {'callback_ordinal': self.callbacks, 'characters': len(text),
                                      'reason': 'characters_per_callback_limit'})
            return
        run = {'id': f"p{self.page['page']}:t{self.callbacks}", 'callback_ordinal': self.callbacks,
               'event_ordinal': self.event, 'text': text, 'text_sha256': contract.sha(text.encode('utf-8')),
               'cm': None, 'tm': None, 'font_name': None, 'font_size': None,
               'coordinate_status': 'parser_coordinates_unverified', 'source_text_span': None}
        self.numeric_field(run, 'cm', cm, 6)
        self.numeric_field(run, 'tm', tm, 6)
        self.numeric_field(run, 'font_size', font_size)
        try:
            name = font.get('/BaseFont') if font is not None else None
            if isinstance(name, str) and len(name) <= 256:
                run['font_name'] = str(name)
        except Exception:
            self.reason('font_metadata_unavailable')
        self.append('runs', run)

    def visit_operator(self, operator, args, cm, tm):
        self.budget.check()
        self.event += 1
        self.operators += 1
        self.budget.counts['operators'] += 1
        if self.operators > self.limits.operators_per_page:
            self.stop('operation_limit')
        if self.budget.counts['operators'] > self.limits.operators_total:
            self.stop('document_operation_limit')
        name = operator.decode('ascii', errors='replace') if isinstance(operator, bytes) else ''
        if name not in KNOWN:
            self.unretained_operators += 1
            return  # Nongeometry operands/objects/actions are never serialized.
        if name in UNSUPPORTED:
            self.reason('unsupported_transform_or_paint')
            if name not in self.page['unsupported_operators']:
                self.page['unsupported_operators'].append(name)
        primitive = {'id': f"p{self.page['page']}:o{self.operators}", 'operator_ordinal': self.operators,
                     'event_ordinal': self.event, 'operator': name, 'operands': [], 'cm': None, 'tm': None,
                     'coordinate_status': 'parser_coordinates_unverified'}
        self.numeric_field(primitive, 'cm', cm, 6)
        self.numeric_field(primitive, 'tm', tm, 6)
        if name in OPERANDS:
            self.numeric_field(primitive, 'operands', args, OPERANDS[name])
        self.append('primitives', primitive)

    def candidate(self, field, evidence_ids, reason):
        count = len(self.page['table_candidates']) + len(self.page['footnote_candidates'])
        if count >= self.limits.regions_per_page or self.budget.counts['regions'] >= self.limits.regions_total:
            self.reason('region_limit')
            self.regions_omitted += 1
            return
        self.append(field, {'id': f"p{self.page['page']}:r{count + 1}", 'status': 'candidate_unreviewed',
                            'evidence_ids': evidence_ids, 'reason': reason, 'association': None})
        self.budget.counts['regions'] += 1

    def candidates(self):
        # These are review pointers, never table cells or footnote associations.
        lines = [item['id'] for item in self.page['primitives'] if item['operator'] in ('l', 're')]
        if len(lines) >= 4 and any(run['text'].strip() for run in self.page['runs']):
            self.candidate('table_candidates', lines[:4], 'repeated_rule_operators_require_table_review')
        for run in self.page['runs']:
            self.budget.check()
            if run['text'].lstrip().startswith(('*', '\u2020', '\u2021')):
                self.candidate('footnote_candidates', [run['id']], 'explicit_marker_text_requires_review')

    def finish(self):
        try:
            self.candidates()
        except PageStop:
            pass
        self.page['observed_counts'] = {'text_callbacks': self.callbacks, 'operator_callbacks': self.operators,
                                        'callback_characters': self.characters,
                                        'unretained_operator_callbacks': self.unretained_operators}
        if self.stopped:
            self.page['remaining_callback_count'] = None
        if self.stopped or 'oversized_callback_omitted' in self.page['reasons']:
            self.page['text_status'] = 'text_observation_incomplete'
        elif any(run['text'].strip() for run in self.page['runs']):
            self.page['text_status'] = 'available_unreviewed'
        else:
            self.page['text_status'] = 'no_text_observed_requires_review'
            self.page['status'] = 'textless_nontext_review_required'
        if self.page['reasons']:
            self.page['status'] = 'partial'
        self.page['region_candidates_omitted'] = self.regions_omitted
        self.page['remaining_region_candidate_count'] = None if self.stopped else 0
        return self.page


def _read_page(reader, number, span, budget):
    collector = PageCollector(number, span, budget)
    try:
        page = reader.pages[number - 1]
        budget.check()
        collector.geometry(page)
        text = page.extract_text(visitor_text=collector.visit_text, visitor_operand_before=collector.visit_operator)
        budget.check()
        if isinstance(text, str) and len(text) > budget.limits.page_characters:
            collector.reason('page_character_limit')
    except LayoutInterrupted:
        raise
    except PageStop:
        pass
    except Exception:
        collector.reason('page_parser_failed')
        collector.stopped = True
    return collector.finish()


def _reader(body, budget):
    try:
        import pypdf
    except ImportError:
        return None, None, 'parser_unavailable', None
    if pypdf.__version__ != contract.PARSER:
        return None, None, 'parser_version_unreviewed', pypdf.__version__
    try:
        reader = pypdf.PdfReader(io.BytesIO(body))
        budget.check()
        if reader.is_encrypted:
            return None, None, 'encrypted', pypdf.__version__
        count = len(reader.pages)
        budget.check()
        return reader, count, None, pypdf.__version__
    except LayoutInterrupted:
        raise
    except Exception:
        return None, None, 'parser_failed', pypdf.__version__


def _selection(page_numbers, count, limits):
    if page_numbers is None:
        return list(range(1, min(count, limits.pages) + 1))
    if (not isinstance(page_numbers, (list, tuple)) or len(page_numbers) > limits.pages
            or any(type(number) is not int or not 1 <= number <= min(count, limits.pages) for number in page_numbers)
            or list(page_numbers) != sorted(set(page_numbers))):
        raise ValueError('invalid_selected_pages')
    return list(page_numbers)


def build_pdf_layout(pdf_bytes: bytes, *, retained: RetainedExtraction, output_dir: Path,
                     page_numbers=None, limits: LayoutLimits | None = None, clock=None) -> dict:
    """Create one private sidecar. Requires external 120-second process isolation."""
    limits = limits or LayoutLimits()
    budget = Budget(limits) if clock is None else Budget(limits, clock)
    binding = retained.verify(pdf_bytes, budget)
    policy = contract.policy_identity(limits)
    budget.check()
    reader, count, reason, parser_version = _reader(pdf_bytes, budget)
    selected = _selection(page_numbers, count, limits) if count is not None else []
    output = contract.create_output(Path(output_dir), budget)
    manifest = {'schema_version': 1, 'kind': 'pdf_layout_manifest', 'status': 'partial',
                'binding': binding, 'policy': policy, 'parser_version': parser_version,
                'pages_total': count, 'pages': [], 'reasons': [reason] if reason else [],
                'alignment_status': 'alignment_unverified', 'table_structure_status': 'unreviewed',
                'footnote_associations_status': 'unreviewed', 'ocr_status': 'not_performed',
                'remaining_callback_count': None, 'unprocessed_page_ranges': [],
                'publication': 'NOT_ATTEMPTED'}
    spans = {span['page']: span for span in retained.coverage['page_spans']}
    written = []
    for number in selected:
        budget.check()
        page = _read_page(reader, number, spans.get(number), budget)
        body = contract.encode(page, limits.page_json_bytes)
        if budget.counts['output'] + len(body) + 128 * 1024 > limits.output_bytes:
            manifest['reasons'].append('output_limit')
            break
        path = output / f'page-{number:04d}.json'
        identity = contract.write_exclusive(path, body, budget)
        contract.verify_file(path, body, identity, budget)
        manifest['pages'].append({'page': number, 'file': path.name, 'bytes': len(body),
                                  'sha256': contract.sha(body), 'status': page['status']})
        written.append((path, identity, manifest['pages'][-1]))
        if any(reason.startswith('document_') for reason in page['reasons']):
            manifest['reasons'].append('document_limit')
            break
    processed = {page['page'] for page in manifest['pages']}
    if count is not None:
        manifest['unprocessed_page_ranges'] = _unprocessed_ranges(count, processed)
        if count > limits.pages:
            manifest['reasons'].append('page_limit')
    manifest['counters_before_manifest'] = dict(budget.counts)
    for path, identity, record in written:
        contract.verify_artifact(path, identity, record, budget)
    if retained.verify(pdf_bytes, budget) != binding or contract.policy_identity(limits) != policy:
        raise ValueError('parent_or_policy_changed')
    budget.check()
    contract.seal_manifest(output / 'manifest.json', contract.encode(manifest, limits.output_bytes), budget)
    return manifest

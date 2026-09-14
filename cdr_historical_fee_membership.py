"""Pure exhaustive membership accounting; never normalize historical prices."""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, InvalidOperation

from cdr_historical_fee_exact import canonical_sha, decode, exact, pointer_escape, sha

IDENTITY_FIELDS = ('sector', 'dataset', 'provider', 'brand', 'product_id',
                   'product_name', 'category', 'last_updated', 'product_key')
EMBEDDED_FIELDS = (('productId', 'product_id'), ('name', 'product_name'),
                   ('productCategory', 'category'), ('lastUpdated', 'last_updated'), ('brand', 'brand'))


def numeric_rate_equal(left, right):
    """Audit a known rate field only; never rescale or replace either value."""
    if type(left) is bool or type(right) is bool:
        return False
    try:
        a, b = Decimal(left), Decimal(right)
        return a.is_finite() and b.is_finite() and a == b
    except (InvalidOperation, TypeError):
        return False


def _index(rows, fields):
    result = defaultdict(list)
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or any(field not in row for field in fields):
            raise ValueError('source_identity_shape_invalid')
        key = tuple(row[field] for field in fields)
        if any(not isinstance(value, (str, int)) or type(value) is bool for value in key):
            raise ValueError('source_identity_type_invalid')
        result[key].append((index, row))
    return result


def _product_reason(product, raw):
    for embedded, field in EMBEDDED_FIELDS:
        if field not in product or embedded not in raw or not exact(product[field], raw[embedded]):
            return 'embedded_product_identity_differs:' + field
    if any(not isinstance(product.get(field), str) for field in IDENTITY_FIELDS):
        return 'product_identity_missing_or_wrong_type'
    if product['product_key'] != '|'.join(product[field] for field in (
            'provider', 'product_id', 'category', 'product_name')):
        return 'qualified_product_identity_differs'
    return None


def account(source, core, details):
    """Return proved products and a disposition for every source/public rate/product."""
    if any(not isinstance(source.get(field), list) for field in ('products', 'rates', 'fees')):
        raise ValueError('source_export_arrays_required')
    if not isinstance(details.get('products'), dict) or set(core.get('sections', {})) != {'Mortgage', 'Savings', 'TD'}:
        raise ValueError('public_payload_shape_invalid')
    products = _index(source['products'], ('product_key',))
    rates = _index(source['rates'], ('product_key', 'rate_family', 'rate_index'))
    flattened = _index(source['fees'], ('product_key', 'item_index'))
    admitted, product_rows, rate_rows, withheld = {}, [], [], {}
    for key in sorted({key[0] for key in products} | set(details['products'])):
        variants = products.get((key,), [])
        reason = 'source_product_missing_or_ambiguous' if len(variants) != 1 else None
        if key not in details['products']:
            reason = 'source_product_not_in_public_details'
        raw = None
        if len(variants) == 1:
            index, product = variants[0]
            encoded = product.get('details_json')
            if not isinstance(encoded, str):
                raise ValueError('embedded_details_must_be_encoded_json_string')
            raw = decode(encoded.encode('utf-8'), limit=16 * 1024**2)
            if not isinstance(raw, dict):
                raise ValueError('embedded_product_must_be_object')
            reason = reason or _product_reason(product, raw)
            detail = details['products'].get(key)
            if isinstance(detail, dict) and 'last_updated' in detail and not exact(detail['last_updated'], product.get('last_updated')):
                reason = 'public_detail_last_updated_conflict'
            admitted[key] = (index, product, raw)
        if reason:
            withheld[key] = [reason]
        product_rows.append({'product_key': key, 'source_product_indices': [item[0] for item in variants],
                             'public_detail_present': key in details['products'], 'reason': reason})
    seen = set()
    for section, content in core['sections'].items():
        if not isinstance(content, dict) or not isinstance(content.get('rates'), list):
            raise ValueError('public_rate_array_required')
        for index, row in enumerate(content['rates']):
            if not isinstance(row, dict) or not isinstance(row.get('product_key'), str):
                raise ValueError('public_rate_identity_shape_invalid')
            key = row['product_key']
            identity = (key, 'lending' if section == 'Mortgage' else 'deposit', row.get('rate_index'))
            valid_index = type(identity[2]) is int and identity[2] > 0
            matches = rates.get(identity, []) if valid_index else []
            reason = 'public_rate_missing_or_ambiguous' if len(matches) != 1 or identity in seen else None
            seen.add(identity)
            retained = matches[0][1] if len(matches) == 1 else None
            if retained:
                if retained.get('dataset') != section or any(
                        field not in retained or not exact(value, retained[field]) for field, value in row.items()):
                    reason = 'public_rate_field_conflict'
                if key not in admitted or any(field not in retained or not exact(retained[field], admitted[key][1].get(field))
                                              for field in IDENTITY_FIELDS):
                    reason = 'source_rate_product_scope_conflict'
            if reason:
                withheld.setdefault(key, []).append(reason)
            evidence = {}
            if key in admitted and valid_index:
                family_field = 'lendingRates' if identity[1] == 'lending' else 'depositRates'
                array = admitted[key][2].get(family_field)
                if isinstance(array, list) and identity[2] <= len(array) and isinstance(array[identity[2] - 1], dict):
                    raw_rate = array[identity[2] - 1]
                    evidence = {'embedded_rate_pointer': f'/{family_field}/{identity[2] - 1}',
                                'embedded_rate_present': 'rate' in raw_rate, 'embedded_rate_value': raw_rate.get('rate'),
                                'retained_public_rate_value': row.get('rate'),
                                'preexisting_embedded_rate_variant': not exact(row.get('rate'), raw_rate.get('rate')),
                                'preexisting_numeric_rate_variant': not numeric_rate_equal(row.get('rate'), raw_rate.get('rate'))}
            rate_rows.append({'public_row_pointer': f'/sections/{section}/rates/{index}', 'product_key': key,
                              'source_rate_indices': [item[0] for item in matches], 'status': 'WITHHELD' if reason else 'EXACT_MATCH',
                              'reason': reason, 'public_row_canonical_sha256': canonical_sha(row), **evidence})
    for identity, variants in rates.items():
        key, family, index = identity
        reason = None
        if len(variants) != 1 or type(index) is not int or index < 1 or family not in ('lending', 'deposit'):
            reason = 'source_rate_identity_invalid_or_ambiguous'
        elif key in admitted:
            array = admitted[key][2].get('lendingRates' if family == 'lending' else 'depositRates')
            if not isinstance(array, list) or index > len(array) or not isinstance(array[index - 1], dict):
                reason = 'embedded_rate_index_unproved'
        else:
            reason = 'source_rate_product_unproved'
        if reason:
            withheld.setdefault(key, []).append(reason)
        if identity not in seen:
            retained = variants[0][1]
            rate_rows.append({'source_rate_indices': [item[0] for item in variants], 'product_key': key,
                              'status': 'SOURCE_ONLY', 'reason': reason or (
                                  'retained_discount_component_excluded' if retained.get('rate_type') == 'DISCOUNT'
                                  else 'projection_relationship_unknown')})
    for row in product_rows:
        row['reasons'] = sorted(set(withheld.get(row['product_key'], [])))
        row['status'] = 'WITHHELD' if row['reasons'] else 'MEMBERSHIP_PROVED'
    return admitted, flattened, product_rows, rate_rows, withheld


def fee_array_binding(key, product, raw, detail, flattened):
    """Full array/flattened alignment precedes any per-fee additive decision."""
    if not isinstance(detail, dict):
        return 'public_detail_not_object', []
    old, fees = detail.get('fees'), raw.get('fees')
    if not isinstance(old, list) or not isinstance(fees, list):
        return 'fee_array_missing_null_or_wrong_type', []
    if len(old) != len(fees) or any(not isinstance(item, dict) for item in old + fees):
        return 'fee_array_length_or_shape_differs', []
    indices = []
    actual = {identity[1] for identity in flattened if identity[0] == key}
    if actual != set(range(1, len(fees) + 1)):
        return 'flattened_fee_indices_do_not_match_complete_array', []
    for index, fee in enumerate(fees):
        rows = flattened.get((key, index + 1), [])
        if len(rows) != 1:
            return 'flattened_fee_identity_ambiguous', []
        flat_index, row = rows[0]
        if type(row['item_index']) is not int or any(field not in row or not exact(row[field], product[field])
                                                    for field in IDENTITY_FIELDS):
            return 'flattened_fee_product_scope_conflict', []
        embedded = row.get('details_json')
        if not isinstance(embedded, str) or not exact(decode(embedded.encode('utf-8')), fee):
            return 'flattened_fee_object_conflict', []
        if 'feeType' not in fee or not exact(row.get('item_type'), fee['feeType']):
            return 'flattened_fee_type_conflict', []
        indices.append(flat_index)
    return None, indices


def product_evidence(index, product, raw):
    return {'source_product_index': index, 'embedded_string_pointer': f'/products/{index}/details_json',
            'embedded_string_utf8_sha256': sha(product['details_json'].encode('utf-8')),
            'embedded_object_canonical_sha256': canonical_sha(raw),
            'identity_fields': {key: {'present': key in product, 'value': product.get(key)} for key in IDENTITY_FIELDS},
            'source_file_reference': {'value': product.get('source_file'), 'status': 'UNVERIFIED_STRING_NOT_DEREFERENCED'},
            'public_product_pointer': '/products/' + pointer_escape(product['product_key'])}

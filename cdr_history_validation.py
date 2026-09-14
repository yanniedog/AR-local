"""Structural and byte binding checks for retained historical audit inputs."""
from datetime import date
import hashlib
import re


def ordered_dates(index):
    dates = index.get('dates') if isinstance(index, dict) else None
    if not isinstance(dates, list) or not dates or any(
            not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value)
            for value in dates):
        raise ValueError('invalid ordered date index')
    if dates != sorted(set(dates)):
        raise ValueError('invalid ordered date index')
    for value in dates:
        date.fromisoformat(value)
    heads = index.get('revision_heads', {})
    if not isinstance(heads, dict) or any(key not in dates or not isinstance(head, dict)
                                         for key, head in heads.items()):
        raise ValueError('invalid selected revision heads')
    return dates


def manifest_shape(value, run_date, *, details=False):
    if not isinstance(value, dict) or value.get('run_date') != run_date:
        raise ValueError('dated manifest structure mismatch')
    files = value.get('files')
    if not isinstance(files, dict):
        raise ValueError('dated manifest files structure mismatch')
    for kind in ('core', 'details') if details else ('core',):
        asset = files.get(kind)
        if not isinstance(asset, dict) or type(asset.get('bytes')) is not int or asset['bytes'] < 0:
            raise ValueError('dated manifest asset structure mismatch')
        if not isinstance(asset.get('sha256'), str) or not re.fullmatch('[0-9a-f]{64}', asset['sha256']):
            raise ValueError('dated manifest asset hash structure mismatch')
        if not isinstance(asset.get('url'), str) or not asset['url']:
            raise ValueError('dated manifest asset URL structure mismatch')
    for key in ('payload_revision', 'source_observation'):
        if key in value and not isinstance(value[key], dict):
            raise ValueError('dated manifest metadata structure mismatch')


def core_shape(value, run_date):
    if not isinstance(value, dict) or value.get('run_date') != run_date:
        raise ValueError('dated core structure mismatch')
    sections = value.get('sections')
    if not isinstance(sections, dict) or set(sections) != {'Mortgage', 'Savings', 'TD'}:
        raise ValueError('dated core sections structure mismatch')
    for content in sections.values():
        rates = content.get('rates') if isinstance(content, dict) else None
        if not isinstance(rates, list) or any(not isinstance(row, dict) or any(
                not isinstance(row.get(key), str) or not row[key] for key in ('product_key', 'provider'))
                for row in rates):
            raise ValueError('dated core rates structure mismatch')


def details_shape(value, run_date, groups):
    if not isinstance(value, dict) or value.get('run_date') != run_date:
        raise ValueError('dated details structure mismatch')
    products = value.get('products')
    if not isinstance(products, dict) or any(not isinstance(detail, dict) or any(
            not isinstance(detail.get(group, []), list) for group in groups)
            for detail in products.values()):
        raise ValueError('dated detail products structure mismatch')


def export_bindings(root):
    return {name: {'bytes': (root / name).stat().st_size,
                   'sha256': hashlib.sha256((root / name).read_bytes()).hexdigest()}
            for name in ('dates.csv', 'bank-product-dates.csv')}


def verified_exports(root, summary):
    """Return the exact verified bytes, so later reads cannot swap the table."""
    bindings = summary.get('exports')
    if not isinstance(bindings, dict):
        raise ValueError('historical audit export bindings missing; rerun audit from pinned assets')
    verified = {}
    for name in ('dates.csv', 'bank-product-dates.csv'):
        expected = bindings.get(name)
        if not isinstance(expected, dict) or type(expected.get('bytes')) is not int:
            raise ValueError('historical audit export binding invalid')
        path = root / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size != expected['bytes']:
            raise ValueError('historical audit export size or file identity mismatch')
        body = path.read_bytes()
        if len(body) != expected['bytes'] or hashlib.sha256(body).hexdigest() != expected.get('sha256'):
            raise ValueError('historical audit export hash mismatch')
        verified[name] = body
    return verified

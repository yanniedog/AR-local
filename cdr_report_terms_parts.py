"""Atomic, bounded multipart terms evidence; all parts share one SQLite snapshot."""
import argparse
import json
import shutil
import tempfile
from pathlib import Path

from cdr_report_terms import (MAX_PRODUCTS, _export_selected, admit_evidence,
                              bundle_binding, delivered, encoded, sha)
from cdr_terms.identity import digest

CONTRACT = 'report-terms-parts-v1'
PART_PRODUCTS = 32
MAX_PARTS = 625
MAX_INDEX_BYTES = 4 * 1024 * 1024
LIMITS = {'bytes': 256 * 1024 * 1024, 'row_bytes': 512 * 1024 * 1024,
          'row_count': 1000000, 'processed_io_bytes': 2 * 1024 * 1024 * 1024,
          'sqlite_steps': 100000000}


def _accumulate(total, part):
    for key, limit in LIMITS.items():
        value = part[key]
        if type(value) is not int or value < 0:
            raise ValueError('Invalid multipart resource receipt')
        total[key] += value
        if total[key] > limit:
            raise ValueError('Multipart aggregate budget exceeded: ' + key)


def _reset_part(view):
    # Keep the same BEGIN transaction, but bound each part independently.
    view.row_bytes = view.count = view.steps = view.processed_io_bytes = 0
    view.identities.clear()
    view.blobs.clear()
    view.max_read_request = view.max_materialized_blob = 0


def export_parts(bundle, store, output, *, technical=False):
    from cdr_product_report import read_bundle
    from cdr_report_admission import admit_new_directory
    bundle, store, output = (Path(p).resolve() for p in (bundle, store, output))
    for source in (bundle, store):
        if output == source or output in source.parents or source in output.parents:
            raise ValueError('Evidence output must be separate from inputs')
    if output.exists():
        raise ValueError('Use a new immutable evidence directory')
    manifest, payloads, evidence = read_bundle(bundle)
    binding, keys = bundle_binding(manifest, payloads, evidence)
    adopted = delivered(bundle, manifest, payloads)
    if set(adopted) - set(keys):
        raise ValueError('Report delivered unknown product')
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.report-parts-', dir=output.parent))
    try:
        index = _write_parts(stage, store, binding, keys, adopted, technical)
        raw = encoded(index)
        if len(raw) > MAX_INDEX_BYTES:
            raise ValueError('Multipart index budget exceeded')
        (stage / 'parts.json').write_bytes(raw)
        # Independently read every sealed part before the single admission.
        verify_parts(stage, binding, keys)
        admit_new_directory(stage, output)
        return {'contract': CONTRACT, 'sha256': sha(raw), 'products': len(keys),
                'parts': len(index['parts']), 'totals': index['totals']}
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def _write_parts(stage, store, binding, keys, adopted, technical):
    from cdr_report_terms_store import Snapshot
    view = Snapshot(store, reuse_verified=True)
    parts, totals = [], dict.fromkeys(LIMITS, 0)
    try:
        # Empty inventories still carry a validated snapshot receipt.
        for start in range(0, max(1, len(keys)), PART_PRODUCTS):
            if len(parts) >= MAX_PARTS:
                raise ValueError('Multipart part budget exceeded')
            _reset_part(view)
            selected = keys[start:start + PART_PRODUCTS]
            name = f'part-{len(parts) + 1:04d}'
            seal = _export_selected(view, binding, selected, adopted, stage / name, technical=technical)
            metrics = {'bytes': seal['bytes'], 'row_bytes': view.row_bytes, 'row_count': view.count,
                       'processed_io_bytes': view.processed_io_bytes, 'sqlite_steps': view.steps}
            _accumulate(totals, metrics)
            parts.append({'name': name, 'keys': selected, 'seal': seal, 'metrics': metrics})
    finally:
        view.close()
    return {'contract': CONTRACT, 'binding': binding, 'parts': parts, 'totals': totals,
            'products': len(keys), 'exporter_sha256': sha(Path(__file__).read_bytes())}


def verify_parts(root, binding, keys):
    """Validate all parts before returning a descriptor; do not merge them in RAM."""
    root = Path(root).resolve()
    path = root / 'parts.json'
    if path.is_symlink() or not 0 < path.stat().st_size <= MAX_INDEX_BYTES:
        raise ValueError('Multipart index budget or path invalid')
    raw = path.read_bytes()
    index = json.loads(raw)
    if (encoded(index) != raw or set(index) != {'contract', 'binding', 'parts', 'totals', 'products', 'exporter_sha256'}
            or index['contract'] != CONTRACT or index['binding'] != binding):
        raise ValueError('Multipart selected identity differs')
    if (not isinstance(index['parts'], list) or not 1 <= len(index['parts']) <= MAX_PARTS
            or not isinstance(keys, list) or len(keys) > MAX_PRODUCTS or len(set(keys)) != len(keys)
            or digest(sorted(keys)) != binding['product_inventory_sha256']):
        raise ValueError('Multipart inventory invalid')
    totals, observed = dict.fromkeys(LIMITS, 0), []
    for ordinal, part in enumerate(index['parts'], 1):
        if (set(part) != {'name', 'keys', 'seal', 'metrics'} or part['name'] != f'part-{ordinal:04d}'
                or not isinstance(part['keys'], list) or len(part['keys']) > PART_PRODUCTS
                or (not part['keys'] and keys)):
            raise ValueError('Multipart part inventory invalid')
        directory = root / part['name']
        if directory.is_symlink() or directory.resolve() != directory:
            raise ValueError('Unsafe multipart part path')
        _accumulate(totals, part['metrics'])
        value, seal = admit_evidence(directory, binding, part['keys'])
        if seal != part['seal'] or seal['bytes'] != part['metrics']['bytes']:
            raise ValueError('Multipart seal differs')
        for metric in ('row_bytes', 'row_count', 'processed_io_bytes'):
            if part['metrics'][metric] != value['snapshot'][metric]:
                raise ValueError('Multipart snapshot receipt differs')
        observed.extend(part['keys'])
    if (observed != sorted(keys) or index['products'] != len(keys) or totals != index['totals']):
        raise ValueError('Multipart complete product inventory differs')
    return index


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('bundle', 'store', 'output'):
        parser.add_argument('--' + name, required=True, type=Path)
    parser.add_argument('--technical', action='store_true')
    args = parser.parse_args()
    print(json.dumps(export_parts(args.bundle, args.store, args.output, technical=args.technical)))


if __name__ == '__main__':
    main()

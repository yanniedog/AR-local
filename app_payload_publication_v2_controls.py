"""Expand only exact, hash-bound local v2 preservation control inventories."""
from app_payload_product_evidence_contract import decode, digest, require
from app_payload_product_evidence_delivery_check import read_stable


def v2_control_inventory(root, *, repo):
    parent = root / 'v2-preservation'
    if not parent.exists(): return {}
    require(parent.is_dir() and not parent.is_symlink(), 'unsafe v2 preservation root')
    from app_payload_v2_archive import read_manifest, archive_tag
    from app_payload_revisions_state import validate_manifest
    inventory = {}; total = 0; count = 0
    def read(path, maximum):
        nonlocal total
        raw, _ = read_stable(path, maximum); total += len(raw)
        require(total <= 128*1024*1024 and len(inventory) < 4096, 'v2 controls exceed budget')
        inventory[path.relative_to(root).as_posix()] = dict(bytes=len(raw), sha256=digest(raw))
        return raw
    for directory in parent.iterdir():
        count += 1
        require(count <= 256 and directory.is_dir() and not directory.is_symlink(), 'invalid v2 archive directory')
        raw = read(directory/'manifest-v2.json', 65536); selector = read_manifest(raw)
        require(directory.name == archive_tag(raw), 'v2 archive identity differs')
        base_raw = read(directory/'base-manifest.json', 8*1024*1024); base = decode(base_raw); validate_manifest(base)
        receipt = decode(read(directory/'preservation.json', 8*1024*1024))
        require(type(receipt) is dict and set(receipt) == {'schema','manifest_sha256','base_manifest_sha256',
                'manifest_file','base_manifest_file','files'} and receipt['schema'] == 'ar-local-v2-preservation-v1'
                and receipt['manifest_sha256'] == digest(raw) and receipt['base_manifest_sha256'] == digest(base_raw)
                and receipt['manifest_file'] == 'manifest-v2.json' and receipt['base_manifest_file'] == 'base-manifest.json',
                'v2 preservation receipt differs')
        entries = [*selector['files'].items(), *((f'base_{kind}', base['files'][kind]) for kind in ('core','details'))]
        require(set(receipt['files']) == {entry['name'] for _,entry in entries}
                and all(base['files'][kind]['sha256'] == selector['base'][kind+'_sha'] for kind in ('core','details')),
                'v2 preserved base/inventory differs')
        for kind, entry in entries:
            expected = dict(kind=kind, sha256=entry['sha256'], bytes=entry['bytes'], source_url=entry['url'],
                archive_url=f"https://github.com/{repo}/releases/download/{directory.name}/{entry['name']}")
            require(receipt['files'][entry['name']] == expected, 'v2 asset receipt differs')
            data = read(directory/entry['name'], min(entry['bytes'], 64*1024*1024))
            require(len(data) == entry['bytes'] and digest(data) == entry['sha256'], 'v2 preserved bytes differ')
    return inventory

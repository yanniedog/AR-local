"""Complete optional byte/route acceptance; never source-population authority."""
from pathlib import Path

from app_payload_product_evidence_contract import canonical, require
from app_payload_product_evidence_reference import LANES, bound_bundle_sha256
from app_payload_publication_assets import has_evidence, verify_stage
from cdr_product_evidence_delivery_policy import STATUS

SCHEMA = 'ar-product-evidence-audit-v1'


def verified_inventory(root, manifest, expected_manifest_sha256):
    """Keep legacy behavior; known optional input requires every actual byte."""
    if not has_evidence(manifest):
        from app_payload_optional_assets import iter_payload_assets
        return dict(iter_payload_assets(manifest)), None
    result = verify_stage(Path(root), expected_manifest_sha256=expected_manifest_sha256)
    require(result['asset_bytes_verified'] is True, 'optional complete byte verification missing')
    require(result['proof']['bundle_sha256'] == bound_bundle_sha256(manifest),
            'optional audit manifest differs from verified inventory')
    inventory = result['inventory'].document()['inventory']
    return inventory, result['proof']


def receipt(manifest, manifest_sha256, inventory, *, scope, selected_head_verified=False,
            public_transport_verified=False):
    """Only call after full verification; absence is not zero product coverage."""
    require(scope in ('private_candidate','public_selected'), 'unknown evidence audit scope')
    require(type(selected_head_verified) is bool and type(public_transport_verified) is bool,
            'invalid evidence audit authority')
    require(scope != 'private_candidate' or not (selected_head_verified or public_transport_verified),
            'private optional candidate cannot claim selection/public transport')
    lanes = {}
    for lane in LANES:
        state = manifest[STATUS]['lanes'][lane]
        count = sum(key.startswith(lane+'_') for key in inventory)
        require((state['state'] == 'available') == (count > 0), 'optional audit lane inventory differs')
        lanes[lane] = {**state, 'verified_asset_count':count}
    return dict(schema=SCHEMA, status='PASS', manifest_sha256=manifest_sha256, scope=scope, lanes=lanes,
        namespace_validation_complete=True, selected_head_verified=selected_head_verified,
        public_transport_verified=public_transport_verified, rendered_coverage_verified=False,
        population_completeness_verified=False, original_wire_bytes_verified=False)


def validate_private_app_receipt(value, manifest, manifest_sha256, inventory):
    expected = receipt(manifest,manifest_sha256,inventory,scope='private_candidate')
    require(type(value) is dict and canonical(value) == canonical(expected),
            'app optional audit lacks exact complete private-candidate proof')


def reject_unsupported_report(manifest):
    if has_evidence(manifest):
        raise ValueError('optional_product_evidence_unsupported_by_legacy_report: no complete report was produced')

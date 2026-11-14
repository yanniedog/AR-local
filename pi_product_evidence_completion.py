"""New optional publisher provenance, never a guess about the financial writer."""
from pathlib import Path
import re

from app_payload_product_evidence_contract import canonical,decode,digest,fields,require,SHA
from app_payload_product_evidence_delivery_check import read_stable
from cdr_atomic import atomic_write_bytes
from pi_product_evidence_retry import DIRECTORY


def validate_writer(value):
    fields(value,('commit','tree','source_closure_sha256','runtime_sha256','profile_sha256'))
    require(all(type(value[key]) is str and re.fullmatch('[0-9a-f]{40}',value[key]) for key in ('commit','tree')),
            'exact optional writer commit/tree required')
    require(all(type(value[key]) is str and SHA.fullmatch(value[key])
                for key in ('source_closure_sha256','runtime_sha256','profile_sha256')),'exact optional writer closure required')


def complete(state,owner,manifest,writer):
    """Called only after real revision and aliases pass their existing readbacks."""
    validate_writer(writer)
    require(writer['commit']==owner.request['pointer']['optional_product_evidence_intent']['writer_revision'],
            'completion writer differs from original optional intent')
    from pi_product_evidence_dispatch import _local_publication
    root,index_raw=_local_publication(state,manifest)
    index_sha=digest(index_raw);head=decode(index_raw)['revision_heads'][manifest['run_date']]
    promotion=root/'promotions'/index_sha/'promotion-receipt.json'
    raw,_=read_stable(promotion,65536)
    manifest_raw,_=read_stable(root/'manifest.json',65536)
    require(head['manifest_sha256']==digest(manifest_raw),'completion manifest differs')
    candidate=owner.progress().get('candidate_pin');require(type(candidate) is dict,'optional frozen candidate pin missing')
    value=dict(schema='ar-product-evidence-publisher-completion-v1',request_sha256=owner.sha256,
        writer=writer,candidate_pin=candidate,selected_head=head,manifest_sha256=digest(manifest_raw),
        promotion=dict(file=promotion.relative_to(state).as_posix(),sha256=digest(raw),bytes=len(raw)),
        predecessor=owner.expected_predecessor,index_sha256=index_sha,
        original_financial_writer=None,rendered_coverage_verified=False,population_completeness_verified=False)
    target=Path(state)/DIRECTORY/'completions'/(owner.sha256+'.json')
    body=canonical(value);atomic_write_bytes(target,body,create_once=True)
    return dict(file=target.relative_to(state).as_posix(),sha256=digest(body),bytes=len(body))

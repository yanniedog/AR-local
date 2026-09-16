"""Default-off monetary route packaging from independently approved publications."""
import json
from app_payload_terms import MAX_PRODUCTS,MAX_SHARD_RAW,MAX_SNAPSHOT_RAW,_json,_ReadView
from cdr_terms.executable_v4_contract import validate_asset,CAPABILITY
from cdr_terms.executable_v4_sources import validate_destination
from cdr_terms.identity import digest
from cdr_terms.executable_v4_publication import build_asset
from cdr_terms.executable_v3_evidence import evidence_operation
from cdr_terms.observation_checks import current_observation
TUPLES = {CAPABILITY}


def load_published_executable_v4(root,*,source_observation,run_date,core_asset_sha256,details_asset_sha256,product_keys):
    keys=set(product_keys)
    if len(keys)>MAX_PRODUCTS:raise ValueError('Monetary product inventory exceeds bound')
    view=_ReadView(root)
    try:
        with evidence_operation(view) as operation:
            result,total={},0
            for capability,key in ((c,k) for c in sorted(TUPLES) for k in sorted(keys)):
                row=view.db.execute('SELECT * FROM executable_publications_v4 WHERE product_key=? AND capability=? ORDER BY sequence DESC LIMIT 1',(key,capability)).fetchone()
                if row is None:continue
                observation=current_observation(view,key)
                if observation['observation_id']!=row['observation_id'] or observation['ingest_id']!=source_observation['generation_id']:
                    raise ValueError('Monetary publication current routing changed')
                if row['state']=='removed':
                    # A tombstone must still agree with current dispositions, never hide unresolved candidates.
                    product=operation.adopted_json(details_asset_sha256).get('products',{}).get(key)
                    if not isinstance(product,dict):raise ValueError('Monetary removal product missing from destination')
                    expected=digest(dict(schemaVersion=4,capability=capability,productKey=key,observationId=observation['observation_id'],state='removed'))
                    if row['identity_sha256']!=expected:raise ValueError('Monetary tombstone identity differs')
                    routing=dict(productKey=key,sourceGenerationId=source_observation['generation_id'],exportContractSha256=source_observation['contract_digest'],runDate=run_date,
                        coreAssetSha256=core_asset_sha256,detailsAssetSha256=details_asset_sha256,productRecordSha256=digest(product))
                    if row['payload_json'] is not None or build_asset(view,key,routing=routing,capability=capability) is not None:raise ValueError('Monetary removed publication changed')
                    continue
                raw=row['payload_json'].encode('utf8');total+=len(raw)
                if len(raw)>MAX_SHARD_RAW or total>MAX_SNAPSHOT_RAW:raise ValueError('Monetary snapshot bound exceeded')
                asset=json.loads(raw);validate_asset(asset,key);routing=asset['routing']
                if (routing['runDate']!=run_date or routing['sourceGenerationId']!=source_observation['generation_id']
                    or routing['exportContractSha256']!=source_observation['contract_digest'] or routing['coreAssetSha256']!=core_asset_sha256 or routing['detailsAssetSha256']!=details_asset_sha256
                    or row['identity_sha256']!=asset['identitySha256'] or asset['capability']!=capability or asset!=build_asset(view,key,routing=routing,capability=capability)):
                    raise ValueError('Monetary published approval/source changed')
                result.setdefault(capability,{})[key]=asset
            return result
    finally:view.db.close()


def package_executable_v4(snapshot,*,core,details,core_asset_sha256,details_asset_sha256,run_date,write_asset):
    if set(snapshot)-set(TUPLES):raise ValueError('Monetary unsupported producer route')
    routes={};total=0;public_total=len(_json(core))+len(_json(details))
    if any(snapshot.values()) and public_total>MAX_SNAPSHOT_RAW:raise ValueError('Monetary adopted public snapshot bound exceeded')
    for capability,products in sorted(snapshot.items()):
        if len(products)>MAX_PRODUCTS:raise ValueError('Monetary product inventory exceeds bound')
        shards,index,group={},{},{}
        def document(values):
            return dict(schema_version=4,capability=capability,run_date=run_date,core_asset_sha256=core_asset_sha256,details_asset_sha256=details_asset_sha256,products=values)
        def write(kind,payload):
            nonlocal public_total
            size=len(_json(payload))
            if size>MAX_SHARD_RAW:raise ValueError('Monetary asset raw bound exceeded')
            if public_total+size>MAX_SNAPSHOT_RAW:raise ValueError('Monetary adopted public snapshot bound exceeded')
            public_total+=size
            descriptor=write_asset(kind,payload)
            if descriptor['bytes']>MAX_SHARD_RAW:raise ValueError('Monetary compressed asset bound exceeded')
            return {k:descriptor[k] for k in ('name','bytes','sha256')}
        def flush():
            if not group:return
            if len(shards)>=999:raise ValueError('Monetary shard count exceeded')
            name=f'monetary_v4_{capability}_shard_{len(shards):03d}'
            shards[name]=write(name,document(dict(group)));index.update({key:name for key in group});group.clear()
        for key,asset in sorted(products.items()):
            validate_asset(asset,key)
            if asset['capability']!=capability:raise ValueError('Monetary route capability differs')
            for item in asset['subjects']:validate_destination(item['subject'],core,details,core_asset_sha256,details_asset_sha256)
            total+=len(_json(asset))
            if total>MAX_SNAPSHOT_RAW:raise ValueError('Monetary total snapshot bound exceeded')
            candidate={**group,key:asset}
            if group and len(_json(document(candidate)))>MAX_SHARD_RAW:flush()
            group[key]=asset
        flush()
        if index:routes[capability]={'index':write(f'monetary_v4_{capability}_index',document(index)),'shards':shards}
    return {'schema_version':4,'capabilities':routes} if routes else None

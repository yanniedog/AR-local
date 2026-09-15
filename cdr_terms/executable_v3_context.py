"""Bind benchmark transport to exact retained immutable public gzip assets."""
from .identity import digest,canonical_json
from .executable_v2_inputs import exact_object
from .executable_v3_contract import CAPABILITY,schema_validate,validate_asset
from .executable_v3_sources import validate_destination
from app_payload_optional_assets import executable_asset_url
from app_payload_network_budget import validate_payload_network_budget


def target_binding(target,subject,core):
    fields=('kind','productKey','productRecordSha256')
    exact_object(target,fields if target.get('kind')=='product' else (*fields,'section','coreRowIndex','rateIndex','rowSha256'),'savings target')
    if target['productKey']!=subject['scope']['productKey'] or target['productRecordSha256']!=subject['routing']['productRecordSha256']:
        raise ValueError('Savings product publication is not verified')
    if target['kind']=='product':return
    if target['kind']!='rate_variant' or target['section']!='Savings':raise ValueError('Savings product publication is not verified')
    rows=core.get('sections',{}).get('Savings',{}).get('rates',[]);index=target['coreRowIndex']
    if type(index) is not int or not 0<=index<len(rows):raise ValueError('Savings product publication is not verified')
    row=rows[index]
    if row.get('product_key')!=target['productKey'] or type(row.get('rate_index')) is not type(target['rateIndex']) or row.get('rate_index')!=target['rateIndex'] or digest(row)!=target['rowSha256']:raise ValueError('Savings product publication is not verified')


def context_binding(context,subject,operation):
    exact_object(context,('manifest','index','shard','selection'),'savings context')
    manifest=context['manifest'];source=subject['routing'];key=subject['scope']['productKey']
    validate_payload_network_budget(manifest,manifest_bytes=len(canonical_json(manifest).encode('utf8')))
    route=manifest['executable_v3']['capabilities'][CAPABILITY]
    executable_asset_url(manifest,route['index'],repo=manifest['repo'])
    if manifest.get('enc') or manifest['run_date']!=source['runDate'] or manifest.get('source_observation',{}).get('generation_id')!=source['sourceGenerationId'] or manifest.get('source_observation',{}).get('contract_digest')!=source['exportContractSha256']:
        raise ValueError('Savings benchmark current routing differs')
    def document(descriptor,kind=None):
        value=operation.adopted_json(descriptor['sha256'])
        raw_size,decoded_size=operation.adopted_sizes[descriptor['sha256']]
        if raw_size!=descriptor['bytes'] or descriptor.get('enc'):raise ValueError('Savings adopted descriptor differs')
        if kind:
            if decoded_size>512*1024:raise ValueError('Savings namespace body bound exceeded')
            schema_validate(value,kind,512*1024)
            if value['run_date']!=source['runDate'] or value['core_asset_sha256']!=source['coreAssetSha256'] or value['details_asset_sha256']!=source['detailsAssetSha256'] or value['capability']!=CAPABILITY:
                raise ValueError('Savings namespace source association differs')
        return value
    core=document(manifest['files']['core']);details=document(manifest['files']['details'])
    validate_destination(subject,core,details,manifest['files']['core']['sha256'],manifest['files']['details']['sha256'])
    index=document(route['index'],'index')
    if index!=context['index'] or not set(index['products'])<=set(details.get('products',{})) or set(index['products'].values())!=set(route['shards']):raise ValueError('Savings index inventory differs')
    shard_key=index['products'][key];selected=None
    for name,descriptor in route['shards'].items():
        shard=document(descriptor,'shard')
        if set(shard['products'])!={p for p,k in index['products'].items() if k==name}:raise ValueError('Savings shard product inventory differs')
        for product,asset in shard['products'].items():
            validate_asset(asset,product)
            if asset['capability']!=CAPABILITY:raise ValueError('Savings shard capability differs')
            for entry in asset['subjects']:validate_destination(entry['subject'],core,details,source['coreAssetSha256'],source['detailsAssetSha256'])
        if name==shard_key:
            if shard!=context['shard']:raise ValueError('Savings retained shard differs')
            selected=shard['products'][key]
    selection=context['selection']
    if selection['subject']!=subject or {'subject':subject,'approval':selection['approval']} not in selected['subjects']:raise ValueError('Savings selection association differs')
    binding=dict(manifestSha256=digest(manifest),edition=manifest['payload_revision']['bundle_sha256'],indexSha256=route['index']['sha256'],shardSha256=route['shards'][shard_key]['sha256'],assetSha256=selected['identitySha256'],coreSha256=source['coreAssetSha256'],detailsSha256=source['detailsAssetSha256'],authorityGraphSha256=subject['authorityGraph']['identitySha256'])
    if selection['edition']!=binding['edition']:raise ValueError('Savings selection edition differs')
    return binding,core

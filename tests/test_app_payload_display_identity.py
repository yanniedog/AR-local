"""Source label projection only; no fabricated financial acceptance."""
from app_payload_details import build_details


def test_exact_supplied_labels_and_raw_category():
    value = build_details([{'product_key':'technical','product_name':' Café 零 ','provider':'Protocol provider',
                           'details_json':{'name':' Café 零 ','brand':'Protocol provider','productCategory':'TRANS_AND_SAVINGS_ACCOUNTS'}}])
    assert value['technical']['displayIdentity'] == {'name':' Café 零 ','provider':'Protocol provider',
        'productCategory':'TRANS_AND_SAVINGS_ACCOUNTS'}


def test_unknown_or_oversized_metadata_does_not_use_product_key():
    value = build_details([{'product_key':'bank|invented-category|invented-name','product_name':'x'*257,
        'provider':False,'details_json':{'productCategory':' '}}])
    assert 'displayIdentity' not in value['bank|invented-category|invented-name']


def test_partial_display_metadata_omits_unknown_members():
    value = build_details([{'product_key':'technical','provider':'Filesystem provider','details_json':{'brand':'Exact provider'}}])
    assert value['technical']['displayIdentity'] == {'provider':'Exact provider'}


def test_normalized_filesystem_labels_are_not_source_metadata():
    value=build_details([{'product_key':'technical','product_name':'Path name','provider':'Path provider','details_json':{}}])
    assert 'displayIdentity' not in value['technical']

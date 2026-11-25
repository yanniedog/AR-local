from app_payload_details import build_details


def test_identical_source_entries_publish_once():
    record = {
        'features': [{'featureType': 'OFFSET'}, {'featureType': 'OFFSET'}, {'featureType': 'REDRAW'}],
        'eligibility': [{'eligibilityType': 'NATURAL_PERSON'}, {'eligibilityType': 'NATURAL_PERSON'}],
        'fees': [{'name': 'Annual fee', 'feeType': 'PERIODIC', 'amount': '395.00'},
                 {'name': 'Annual fee', 'feeType': 'PERIODIC', 'amount': '395.00'}],
    }
    detail = build_details([{'product_key': 'bank|x|y|z', 'details_json': record}])['bank|x|y|z']
    assert [item['label'] for item in detail['features']] == ['OFFSET', 'REDRAW']
    assert len(detail['eligibility']) == 1
    assert len(detail['fees']) == 1


def test_distinct_entries_survive():
    record = {'fees': [{'name': 'Annual fee', 'feeType': 'PERIODIC', 'amount': '395.00'},
                       {'name': 'Annual fee', 'feeType': 'PERIODIC', 'amount': '0.00'}]}
    detail = build_details([{'product_key': 'bank|x|y|z', 'details_json': record}])['bank|x|y|z']
    assert len(detail['fees']) == 2

"""Bind a reviewed removal to complete, current replacement evidence and scope."""
from .identity import canonical_json
from .observation_checks import current_observation, selected_check


def require_replacement(store, product_key, before_revision_id, evidence, observed):
    """Caller holds an immediate transaction through change insertion.

    The independent reviewer remains responsible for legal replacement scope;
    a successful fetch or complete extraction alone never proves term removal.
    """
    if evidence.get('full_replacement_validated') is not True:
        raise ValueError('Disappearance/fetch failure cannot prove term removal')
    term = store.db.execute('SELECT * FROM term_revisions WHERE term_revision_id=?',
                            (before_revision_id,)).fetchone()
    keys = evidence.get('replacement_parameter_keys')
    if (canonical_json(evidence.get('replacement_applicability')) != term['applicability_json']
            or not isinstance(keys, list) or not keys or any(not isinstance(k, str) for k in keys)
            or len(keys) != len(set(keys)) or term['parameter_key'] not in keys):
        raise ValueError('Replacement must cover the exact prior applicability and parameter')
    observation = current_observation(store, product_key)
    if observation['observation_id'] != evidence.get('replacement_observation_id'):
        raise ValueError('Replacement must bind the current product observation')
    version = store.db.execute(
        'SELECT v.*,x.text_sha256,x.observed_at AS extracted_at FROM document_versions v JOIN extractions x USING(document_version_id) '
        'WHERE v.document_version_id=? AND x.extraction_id=? AND x.status=\'complete\' '
        'AND EXISTS (SELECT 1 FROM applicability a WHERE a.document_id=v.document_id AND a.observation_id=?)',
        (evidence.get('replacement_document_version_id'), evidence.get('replacement_extraction_id'),
         observation['observation_id'])).fetchone()
    if not version or version['extracted_at'] > observed:
        raise ValueError('Replacement needs the exact complete extraction and observation applicability')
    check = selected_check(store, observation, version['document_id'])
    if (not check or check['status'] not in {'fetched', 'unchanged'}
            or check['document_version_id'] != version['document_version_id']
            or check['checked_at'] > observed):
        raise ValueError('Replacement acquisition must be current, successful and precede removal')
    store.read_blob(version['content_sha256'])
    store.read_blob(version['text_sha256'])
    store.read_blob(observation['source_sha256'])

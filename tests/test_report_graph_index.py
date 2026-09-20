"""Read-only graph report lookup and additive index upgrade; no bank acceptance."""
import sqlite3

from cdr_report_terms_store import Snapshot
from cdr_terms.store import EvidenceStore
from tests.test_cdr_terms_graph import retained, start


def test_graph_index_upgrade_preserves_rows_and_read_only_report(retained):
    store, observation, _ = retained
    root, _, _ = start(retained, '<html><p>Traversal boundary only.</p></html>')
    # Model an existing evidence archive created before the additive index.
    store.db.execute('DROP INDEX document_graph_scope_applicability')
    store.db.commit()
    before = [tuple(row) for row in store.db.execute(
        'SELECT * FROM document_graph_scopes ORDER BY root_id,applicability_id')]
    store_root = store.root
    with EvidenceStore(store_root) as upgraded:
        assert [r[2] for r in upgraded.db.execute(
            'PRAGMA index_info(document_graph_scope_applicability)')] == ['applicability_id', 'root_id']
        assert [tuple(row) for row in upgraded.db.execute(
            'SELECT * FROM document_graph_scopes ORDER BY root_id,applicability_id')] == before
    snapshot = Snapshot(store_root)
    try:
        graph = snapshot.graph(observation)
        assert graph['status'] == 'reported'
        assert {row['root_id'] for row in graph['nodes']} == {root}
        assert snapshot.graph('unselected-observation')['status'] == 'not_reported'
        assert snapshot.view.db.execute('PRAGMA query_only').fetchone()[0] == 1
        try:
            snapshot.view.db.execute('DROP INDEX document_graph_scope_applicability')
        except sqlite3.OperationalError as error:
            assert 'readonly' in str(error)
        else:
            raise AssertionError('Report unexpectedly permits schema writes')
    finally:
        snapshot.view.db.close()


def test_observation_lookup_uses_both_join_indexes(tmp_path):
    with EvidenceStore(tmp_path / 'store') as store:
        plan = store.db.execute(
            'EXPLAIN QUERY PLAN SELECT DISTINCT s.root_id FROM document_graph_scopes s '
            'JOIN applicability a USING(applicability_id) WHERE a.observation_id=? '
            'ORDER BY s.root_id', ('observation',)).fetchall()
        details = '\n'.join(row[3] for row in plan)
        assert 'SEARCH a ' in details
        assert 'SEARCH s USING COVERING INDEX document_graph_scope_applicability' in details
        assert 'SCAN s' not in details

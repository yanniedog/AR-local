"""Source-review actor boundaries, using actual staging and append-only reviews."""
import pytest

from cdr_terms.identity import canonical_json, digest
from cdr_terms.revisions import REVIEW_CHECKS, review_term, stage_term
from tests.test_cdr_terms_evidence import NOW, _staged_term, evidence  # noqa: F401


@pytest.mark.parametrize("interpreter,reviewer", [
    ("worker", " worker "), (" worker ", "worker"),
    ("\tworker\n", " worker\t"),
])
@pytest.mark.parametrize("status", ["validated", "rejected"])
def test_whitespace_equivalent_source_reviewer_is_not_independent(evidence, interpreter, reviewer, status):
    store = evidence[0]
    _, _, _, args = _staged_term(evidence)
    term = stage_term(store, **dict(args, interpreter=interpreter))
    with pytest.raises(ValueError, match="separate reviewer"):
        review_term(store, term, status=status, reviewer=reviewer, reviewer_kind="human",
                    reviewed_at=NOW, evidence_sha256="0" * 64, reason="Actor boundary control")
    assert store.db.execute("SELECT count(*) FROM reviews").fetchone()[0] == 0
    assert store.db.execute("SELECT interpreter FROM term_revisions WHERE term_revision_id=?",
                            (term,)).fetchone()[0] == interpreter


@pytest.mark.parametrize("actor", ["", " \t\n", None, 7])
def test_blank_or_nontext_source_actor_cannot_stage_or_review(evidence, actor):
    store = evidence[0]
    _, _, _, args = _staged_term(evidence)
    with pytest.raises(ValueError, match="interpreter identity"):
        stage_term(store, **dict(args, interpreter=actor))
    assert store.db.execute("SELECT count(*) FROM term_revisions").fetchone()[0] == 0
    term = stage_term(store, **args)
    with pytest.raises(ValueError, match="separate reviewer"):
        review_term(store, term, status="validated", reviewer=actor, reviewer_kind="human",
                    reviewed_at=NOW, evidence_sha256="0" * 64, reason="Actor boundary control")
    assert store.db.execute("SELECT count(*) FROM reviews").fetchone()[0] == 0


def test_distinct_source_reviewer_preserves_actor_spelling_and_idempotency(evidence):
    store = evidence[0]
    _, _, _, args = _staged_term(evidence)
    args["interpreter"] = " worker "
    term = stage_term(store, **args)
    assert stage_term(store, **args) == term
    proof = store.put_blob(canonical_json({"term_revision_id": term, "passed": True,
                                          "checks": sorted(REVIEW_CHECKS)}).encode("utf-8"))
    kwargs = dict(status="validated", reviewer=" independent ", reviewer_kind="human",
                  reviewed_at=NOW, evidence_sha256=proof, reason="Technical identity control only")
    review = review_term(store, term, **kwargs)
    assert review_term(store, term, **kwargs) == review
    assert store.db.execute("SELECT reviewer FROM reviews WHERE review_id=?", (review,)).fetchone()[0] == " independent "
    assert store.db.execute("SELECT count(*) FROM reviews").fetchone()[0] == 1


def test_legacy_blank_interpreter_cannot_receive_new_review(evidence):
    store = evidence[0]
    _, _, _, args = _staged_term(evidence)
    valid = stage_term(store, **args)
    fields = list(store.db.execute("SELECT * FROM term_revisions WHERE term_revision_id=?",
                                   (valid,)).fetchone())[1:]
    # Reproduce the old stage_term insertion for an actor it admitted. Append a
    # content-derived legacy row; never update existing append-only history.
    fields[-2] = " \t "
    legacy = digest([*fields, sorted(args["clause_ids"])])
    with store.db:
        store.db.execute("INSERT INTO term_revisions VALUES (?,?,?,?,?,?,?,?,?,?)", (legacy, *fields))
        for clause in args["clause_ids"]:
            store.db.execute("INSERT INTO term_sources VALUES (?,?)", (legacy, clause))
    with pytest.raises(ValueError, match="separate reviewer"):
        review_term(store, legacy, status="validated", reviewer="independent", reviewer_kind="human",
                    reviewed_at=NOW, evidence_sha256="0" * 64, reason="Legacy actor boundary control")
    assert store.db.execute("SELECT count(*) FROM reviews").fetchone()[0] == 0
    assert store.db.execute("SELECT interpreter FROM term_revisions WHERE term_revision_id=?",
                            (legacy,)).fetchone()[0] == " \t "

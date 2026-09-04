"""Deterministic holder catalogue and detail reconciliation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from cdr_contracts import canonical_json_bytes


def _declared_total(payload: Mapping[str, Any]) -> int | None:
    meta = payload.get("meta")
    if not isinstance(meta, Mapping) or "totalRecords" not in meta:
        return None
    value = meta["totalRecords"]
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("meta.totalRecords must be a non-negative integer")
    return value


@dataclass
class ProductPopulation:
    """Track whether a provider's product population is exactly known."""

    provider_uid: str
    identity_status: str
    pages_attempted: int = 0
    pages_fetched: int = 0
    product_records_observed: int = 0
    terminal_page_reached: bool = False
    relevant_product_ids: set[str] = field(default_factory=set)
    out_of_scope_product_ids: set[str] = field(default_factory=set)
    unresolved_product_ids: set[str] = field(default_factory=set)
    resumed_detail_ids: set[str] = field(default_factory=set)
    successful_detail_ids: set[str] = field(default_factory=set)
    terminal_detail_failures: set[str] = field(default_factory=set)
    _products: dict[str, bytes] = field(default_factory=dict)
    _declared_totals: set[int] = field(default_factory=set)
    _duplicate_ids: set[str] = field(default_factory=set)
    _duplicate_conflicts: set[str] = field(default_factory=set)
    _malformed_products: int = 0
    _population_errors: set[str] = field(default_factory=set)

    def page_attempted(self) -> None:
        self.pages_attempted += 1

    def page_fetched(self, payload: Mapping[str, Any]) -> None:
        self.pages_fetched += 1
        try:
            declared = _declared_total(payload)
        except ValueError:
            self.fail_population("invalid_declared_total")
        else:
            if declared is not None:
                self._declared_totals.add(declared)
                if len(self._declared_totals) > 1:
                    self.fail_population("inconsistent_declared_total")

    def product(self, product: Any, product_id: str) -> bool:
        """Record a product; return True only for a new, valid product ID."""

        self.product_records_observed += 1
        if not isinstance(product, Mapping) or not product_id:
            self._malformed_products += 1
            self.fail_population("malformed_product")
            return False
        encoded = canonical_json_bytes(product)
        previous = self._products.get(product_id)
        if previous is not None:
            self._duplicate_ids.add(product_id)
            self.fail_population("duplicate_product_id")
            if previous != encoded:
                self._duplicate_conflicts.add(product_id)
                self.fail_population("duplicate_product_conflict")
            return False
        self._products[product_id] = encoded
        return True

    def fail_population(self, code: str) -> None:
        self._population_errors.add(str(code))

    def finish_pages(self, *, terminal_page_reached: bool) -> None:
        self.terminal_page_reached = terminal_page_reached
        if len(self._declared_totals) == 1:
            declared = next(iter(self._declared_totals))
            if declared != len(self._products):
                self.fail_population("declared_total_mismatch")

    @property
    def population_known(self) -> bool:
        return self.terminal_page_reached and not self._population_errors

    def mark_relevant(self, product_id: str) -> None:
        self._prepare_classification(product_id)
        self.relevant_product_ids.add(product_id)

    def mark_out_of_scope(self, product_id: str) -> None:
        self._prepare_classification(product_id)
        self.out_of_scope_product_ids.add(product_id)

    def mark_unresolved(self, product_id: str) -> None:
        self._prepare_classification(product_id)
        self.unresolved_product_ids.add(product_id)

    def _prepare_classification(self, product_id: str) -> None:
        if product_id not in self._products:
            raise ValueError("cannot classify an unobserved product")
        self.relevant_product_ids.discard(product_id)
        self.out_of_scope_product_ids.discard(product_id)
        self.unresolved_product_ids.discard(product_id)

    def mark_resumed(self, product_id: str) -> None:
        self.resumed_detail_ids.add(product_id)
        self.successful_detail_ids.add(product_id)

    def mark_detail(self, product_id: str, ok: bool) -> None:
        if ok:
            self.successful_detail_ids.add(product_id)
            self.terminal_detail_failures.discard(product_id)
        else:
            self.terminal_detail_failures.add(product_id)

    def summary(self) -> dict[str, Any]:
        unique = len(self._products)
        relevant = len(self.relevant_product_ids)
        unresolved = self.unresolved_product_ids | (
            set(self._products)
            - self.relevant_product_ids
            - self.out_of_scope_product_ids
            - self.unresolved_product_ids
        )
        present = len(self.successful_detail_ids & self.relevant_product_ids)
        if self.pages_fetched == 0 and not self.population_known:
            state = "failed"
        elif (
            not self.population_known
            or present != relevant
            or self.terminal_detail_failures
            or unresolved
        ):
            state = "partial"
        elif relevant == 0:
            state = "empty"
        else:
            state = "complete"
        declared = next(iter(self._declared_totals)) if len(self._declared_totals) == 1 else None
        return {
            "schema_version": 1,
            "provider_uid": self.provider_uid,
            "identity_status": self.identity_status,
            "state": state,
            "population_known": self.population_known,
            "pages_attempted": self.pages_attempted,
            "pages_fetched": self.pages_fetched,
            "terminal_page_reached": self.terminal_page_reached,
            "declared_total_records": declared,
            "product_records_observed": self.product_records_observed,
            "unique_product_ids": unique,
            "duplicate_product_ids": sorted(self._duplicate_ids),
            "duplicate_conflicts": sorted(self._duplicate_conflicts),
            "malformed_products": self._malformed_products,
            "population_errors": sorted(self._population_errors),
            "relevant_products": relevant,
            "out_of_scope_products": len(self.out_of_scope_product_ids),
            "classification_unresolved": sorted(unresolved),
            "details_present": present,
            "resumed_details": len(self.resumed_detail_ids),
            "terminal_detail_failures": sorted(self.terminal_detail_failures),
        }

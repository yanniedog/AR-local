"""Disk-coordinated current facts; unchanged per-product semantic diff."""
from cdr_product_changes import _append_product_diff, _EVENT_ORDER, SCHEMA_VERSION
from cdr_product_facts import NORMALIZATION_VERSION


class EventSink:
    def __init__(self, store, convert): self.store, self.convert = store, convert

    def append(self, event):
        key = (event['provider'].casefold(), event['product_id'], event['dataset'],
               _EVENT_ORDER[event['event_type']], event['canonical_key'], event['event_id'])
        self.store.append_change(self.convert(event), key)

    def extend(self, events):
        for event in events: self.append(event)


def diff_current_store(previous_groups, store, *, previous_run_date, current_run_date, convert):
    current_count = store.product_count(); previous_count = joined_count = 0
    sink = EventSink(store, convert)
    for key, old in previous_groups:
        current = store.take_product(key)
        previous_count += 1
        if current is not None: joined_count += 1
        _append_product_diff(sink, key, old, current)
    for key in store.product_keys(unmatched=True):
        _append_product_diff(sink, key, None, store.product(key))
    store.changes.seal()
    return dict(schema_version=SCHEMA_VERSION, normalization_version=NORMALIZATION_VERSION,
                previous_run_date=previous_run_date, run_date=current_run_date, current_run_date=current_run_date,
                products=dict(previous=previous_count, current=current_count, joined=joined_count),
                change_count=len(store.changes))

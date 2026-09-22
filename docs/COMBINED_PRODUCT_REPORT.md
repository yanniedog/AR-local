# Combined offline product report

Generate a private, searchable report from a verified immutable payload bundle
and the complete sealed multipart terms export:

```sh
python -m cdr_product_report_parts --bundle <bundle> --terms-evidence <sealed-parts> --output <new-directory>
```

Open `index.html` directly in a browser. Search all products by bank or name;
each product link opens its exact part. Within a part, search every published
field, rate and evidence record. Fields expand on demand. No server, network
request, source mutation or publication is performed.

Each part includes the complete JSON in gzip form, an HTML representation,
product-summary CSV, exact rate-record CSV, detail-pointer CSV and terms CSV.
Large detail and terms tables use gzip. Rates include canonical `record_json`
so null, empty, false and numeric types remain distinguishable. Formula-like
CSV text is escaped; JSON retains the exact original value.

The index also links every supplied metadata/auxiliary-asset leaf, with its
original JSON pointer and typed value. Rate and product records already present
in product parts are not duplicated in these metadata files. Bank and field
inventories retain their measured denominators. Definitions distinguish
published values, derived counts and unavailable financial conclusions.

One selected edition binds all inputs and parts. The exporter rejects missing,
corrupt, differently bound or incomplete evidence, unsafe paths, and an existing
output directory. It checks all emitted hashes and product/rate inventory before
atomic admission. The manifest records code hashes, source hashes, counts and
resource totals. Interrupted or rejected output is never admitted as complete.

Limits: 128 input assets, 16 MiB per compressed input, 128 MiB aggregate compressed
input, 96 MiB per decoded input and 256 MiB aggregate decoded input. Outputs are
limited to 24 MiB per expanded file, 256 MiB aggregate stored bytes, 1 GiB aggregate
expanded bytes and 5,000 files. Metadata chunks have at most 5,000 rows and target
2 MiB; nesting is limited to 64 and metadata/detail inventories to two million
leaves. Oversized individual records fail explicitly rather than being truncated.

This report verifies the supplied inventory. It does not infer unavailable
history, legal completeness, bank approval, customer fees or financial totals.
Installed-app integration and Pi runtime acceptance remain separate.

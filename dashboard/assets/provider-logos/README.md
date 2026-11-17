# Provider artwork for mobile payloads

AR-local embeds these PNGs in the hash-verified mobile core. The pack combines
the sourced banking artwork imported from AR-app with additional banking and
non-bank lending artwork from the CDR Register and provider publications.
`sources.json` records the original source, source hash, and packaged PNG hash.
Its aliases represent verified alternate labels for the same brand.

When a payload build reports missing artwork, use the named provider's CDR
Register entry or official publication to find its mark. Add the bounded PNG
and provenance together. If the provider already has artwork in the pack, add
an explicit alias. The builder logs providers without artwork and embeds
deterministic monograms for them so the downloaded core can render offline.

For an uncached current provider, publication looks up its exact brand in the
CDR Register and tries its `logoUri` first. On placeholder or image failure
it checks the brand website listed in the ACCC's Find a Provider directory
for declared artwork. When that listing is absent, inferred homepages must identify the provider in their title. The worker uses bounded
public HTTPS, retries on later runs, and caches verified PNGs under
`state/provider-artwork-v1/`. Cached artwork is reused offline. All shipped
images use a 112 × 112 canvas. Publication uses embedded monograms when artwork
is unavailable or would exceed the core transfer budget. SVG acquisition
uses `rsvg-convert`, installed alongside Pillow by the Pi installer.

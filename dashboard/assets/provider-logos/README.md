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

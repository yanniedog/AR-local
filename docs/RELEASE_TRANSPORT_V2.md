# Encrypted release transport (ARE2)

ARE2 is an outer transport around the exact existing domain asset bytes. Domain
schemas, compressed sizes, SHA-256 values, revision identities and financial
facts remain unchanged. A manifest itself is also encrypted. Asset names and
GitHub metadata remain operational references; they do not contain dataset bodies.

| Bytes | Meaning |
|---|---|
| 0–3 | ASCII `ARE2` |
| 4–35 | 32 lowercase ASCII hex characters identifying the key |
| 36–43 | Original encoded byte length, unsigned big-endian |
| 44–55 | Random 96-bit nonce |
| 56 onward | AES-256-GCM ciphertext followed by its 16-byte tag |

The first 44 bytes are authenticated additional data. The key ID is the first
16 bytes of SHA-256 over ASCII `ar-local-payload-key:` followed by the 32-byte key.
Overhead is exactly 72 bytes. Readers check the header, exact wire length and
caller-specific decoded limit before key access/decryption. The global encoded
limit is 256 MiB; individual domain contracts impose smaller limits. Existing
bounded decompression and domain-hash verification follow transport decryption.

## Keys and publication

Publication reads the existing private key file selected by
`AR_LOCAL_PAYLOAD_KEY_FILE` (default `/etc/ar-local/payload.key`). The legacy
`AR_LOCAL_PAYLOAD_ENC=0` setting cannot opt publication out of encryption. Retained
keys are read from `AR_LOCAL_PAYLOAD_KEYRING_DIR/<key-id>.key`, defaulting to
`/etc/ar-local/payload-keys`. Key IDs are verified against the loaded key.
Never commit a key, put it in an APK/config, or print it in logs or reports.

The native app imports a private JSON setup document containing exactly
`schema_version: 1`, `key_id` and `key_hex` (64 hex characters). The key ID must
match the key. Import verifies device secure-storage writes and retains previous
keys. The importer also accepts the older 8-character ID, retaining both aliases.
The document must be delivered privately; it is not a release asset.

`app_payload_secure_upload.py` classifies every allowed filename before invoking
GitHub. Unknown classifications, missing keys, invalid ciphertext and legacy ARE1
input fail closed. ARE1 assets need an explicitly verified higher-revision
migration; silently rewriting their frozen domain identity is prohibited.

Ordinary publication verifies encrypted public bytes, including existing
content-addressed names. A matching plaintext hash is insufficient. Legacy
plaintext reads remain available solely for preservation/migration. Automatic
pruning is disabled. The dormant v3 backend encrypts candidate assets and control
documents, authenticates draft readback before its domain census, and preserves
its existing activation/parity locks. Its validated operational lease is the
only unencrypted control document.

## Cutover gate

For a privately preserved and verified historical bundle, the revision publisher
accepts explicit `migrate_encryption=True`. An unchanged selected domain bundle
is reused only when its manifest, every registered asset and the dates index
authenticate as ARE2 and decode to the already validated exact bytes. Legacy
plaintext triggers a higher immutable revision; missing assets, authentication
failures, mismatched bytes and oversized transport remain fatal. Retrying a
completed migration does not create another revision. Existing plaintext legacy
preservation archives remain untouched; migration archives use a deterministic,
separate ARE2 preservation namespace. Default publication behavior is unchanged.
Hold the outer production lock throughout revision publication and alias updates;
historical alias updates must never replace a newer rolling head. This option
does not waive private preservation, compatible-consumer or activation gates.

This code does not authorize activation or removal. Complete a private,
hash-verified inventory (including nested archives and APK contents), preserve
release metadata outside Drive, and verify the compatible signed/released APK
against encrypted current and historical candidates first. Then activate the
reviewed publisher in an ingest-safe Pi window with the Drive hold intact.
Publish higher encrypted historical revisions without rolling the current head
backward. Remove plaintext only after replacement verification and a final full
inventory. Preserve consumed failures and prohibited historical inputs; missing
evidence remains an explicit blocker. Local user-generated reports are never
automatically attached to releases.

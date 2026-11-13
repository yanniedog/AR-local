# Financial provider discovery repair

Current official register contains 115 banking, 191 non-bank-lending and 84 energy brands. The banking-only industry filter silently excluded every non-bank lender even though they use the Banking Product APIs and can supply relevant mortgages. The current 360 MMS endpoint returns 12 RESIDENTIAL_MORTGAGES products using Get Products v5. Official rollout: https://www.cdr.gov.au/rollout/cdr-non-bank-lenders-sector .

The parser now includes both financial industries and keeps energy/unknown industries outside scope. Existing bank names, endpoint normalization, identity construction, category selection, raw capture, pagination, retry limits and holder filters remain. The historical `banking_brands` field and `--banks-only` flag remain compatible names, now documented as the financial API scope. Discovery does not imply every lender supplies mortgages or valid responses.

Real captured register/index fixtures bind the 306-brand scope, preserve all 115 existing banks and demonstrate existing mortgage classification for the 12 observed NBL products. Tests are local replay, not full Pi capture acceptance.

**Activation gate:** do not deploy this expansion based solely on the previous 115-provider retained replay. Run a new resource-guarded real financial-provider capture in an isolated candidate; measure all pages/detail requests, run duration, peak memory/storage and resulting payload sizes. Verify complete attempted-provider accounting and the ordinary resource/quiet-window controls. The extra 191 brands may share backends but must retain distinct identities; don't collapse them or multiply retries without evidence. Preserve any old accepted production/backup until exact-source tests, current canary, publication checks and recovery gates pass.

No Pi, service, schedule or backup mutation is performed by this source patch. All-bank and NBL live acceptance, provider error repair, physical/Drive restore and consumer comparison/watchlist behavior remain separate checks. Do not report 306 complete providers merely because 306 were discovered.

Local validation: 99 tests passed across financial register, ingest status, official single-page recovery, ingest recovery and compatibility suites; `git diff --check` passed. Full exact-head producer/platform CI is pending. Worktree: `C:/code/AR-local-financial-provider-discovery-20261113`, branch `agent/financial-provider-discovery-20261113`. Original public response bytes/UTF-8 representations and provenance hashes are under `tests/fixtures/cdr-financial-register-20261113/`.

## Summary
- Sync `source` to `remote` on up-to-date refresh so in-memory state matches cached live payload.
- Hide the sample-connect banner when refresh is not active via `resolveOfflineBanner`; live progress UI while `refreshing` is unchanged (PR #166).
- Add unit tests for banner visibility and refresh lifecycle.

## Root cause
`OfflineBanner` rendered whenever `source === 'sample'`, including after refresh finished with the static copy "connecting for the latest…". The `upToDate` refresh path updated `manifest` only, never flipping `source` from `sample` to `remote`.

## Test plan
- [x] `npm run typecheck`
- [x] `npm run lint`
- [x] `npm test -- --ci` (77 tests)

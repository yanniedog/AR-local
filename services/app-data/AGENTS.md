# App data delivery service

This isolated HTTPS service delivers AR-local release data to AR-app without user
key setup. It does not deploy the Pi or the AustralianRates website/API.
The approved automatic-access migration is an exception to the repository's
historical no-Cloudflare deployment default for this directory only.

No package installation is required for verification. Run:
`node --test services/app-data/worker.test.mjs`.
Hosted CI uses Node24. Use guarded repository PR gates before deployment.
Keep RELEASE_KEYS exclusively in hosting secret storage. Never publish secrets,
unencrypted GitHub assets or a public key-returning endpoint. Read README.md for
deployment and rollback; distinguish service deployment from installed-app proof.

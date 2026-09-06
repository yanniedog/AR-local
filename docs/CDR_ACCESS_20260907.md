# September 7, 2026 public CDR access investigation

Checks used the current CDR register and real public product requests. The
follow-up probes below ran at 06:35 Australia/Hobart. These are observations
at that time, not a permanent list of unavailable providers.

| Provider | Observed response | Access investigation |
| --- | --- | --- |
| Geelong Bank | HTTP 400, API-key error | Official public endpoint also fails with the documented trailing slash. |
| Hume Bank | HTTP 400, API-key error | Current registered public product endpoint fails. |
| Police Credit Union Ltd | HTTP 400, API-key error | Official lowercase path also fails. |
| QBANK | HTTP 400, API-key error | Current registered public product endpoint fails. |
| Unity Bank | HTTP 400, API-key error | Alternate endpoint linked from its public API page also fails. |
| Aussie Home Loans | HTTP 404 | Register has no explicit product base URI; broker products are not a verified substitute for the account catalog. |
| Darling Downs Bank | DNS failure | No working official alternative found. |
| DDH Graham | HTTP 500, DBAS041 | Server reports failure getting a response from the data holder. |
| Family First | HTTP 503 | Older officially listed endpoint returns HTTP 403; successor coverage requires separate verification. |

The five API-key responses contain the same service error. This suggests a
provider or shared backend configuration problem, but its internal cause is
unconfirmed. No documented client key enrollment was found. No keys were
obtained, and no external messages or forms were submitted.

The [CDR product endpoint guide](https://www.cdr.gov.au/for-providers/how-find-data-holders-product-data-request-service)
and [product reference data guidance](https://cdr-support.zendesk.com/hc/en-us/articles/900004104506-Product-Reference-Data)
describe public product access. [Geelong Bank](https://geelongbank.com.au/access/open-banking/)
and [Unity Bank](https://www.unitybank.com.au/about-us/corporate-information/public-apis/)
also describe public access without customer authentication. Supplying guessed
credentials would not be a supported fix.

[Family First merged with Beyond Bank](https://www.beyondbank.com.au/news/corporate-announcements/family-first-merger-update/),
with its system migration in June 2026. [DDH Graham's BOQ money market notice](https://ddhgraham.au/money-market/boq/)
says new accounts ceased in December 2025 and existing accounts close in November
2026. These facts warrant checking catalog succession and active product scope;
they do not prove that every missing product is covered elsewhere. Preserve
both failures until the register or a validated complete catalog resolves them.

The ingest must continue retrying failed providers using the fresh register,
retain verified observations and their capture dates, and keep source failures
visible. Never convert a failed index request into a successful empty catalog.

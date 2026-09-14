# PDF page evidence

PDF extraction records the actual parser version, physical page ordinals, exact text offsets and hashes, textless/unreadable page dispositions, and explicit unprocessed page ranges. A corrupt or oversized page does not discard successfully extracted sibling pages. Printed URLs and URI annotations are candidate references with page provenance; no PDF action is executed. Wrapped or indirect references remain subject to review.

PDF status remains partial. Textless pages may be blank or carry scanned content; they are not automatically declared blank or sent through unverified OCR. Tables, footnote associations, layout and incorporated documents remain unreviewed. Physical page ordinals are not inferred printed page labels. Page-qualified clauses must fit one retained page span and its exact hash; a guessed page, cross-page range or separator is refused. Unqualified text offsets remain available for existing evidence.

The optional document runtime pins pypdf in requirements-terms.txt. Product CI installs it so protocol tests run rather than skip. Ingest does not install packages. The Pi's installed dependency inventory and controlled runtime activation are separate gates.

Limits: 16 MiB input, 512 processed pages, 100,000 characters per page, 2,000,000 total text characters and 256 retained candidate links. Excess pages/links and failed pages remain explicit. These are input/output accounting limits, not a hard bound on parser internal allocations or a blocked native operation. The existing low-priority supervised child, resource limits and critical ingest windows remain mandatory.

Acceptance uses a retained current official document, not fabricated bank data. Generic protocol PDFs test corruption, encryption, page/link limits and locator integrity. A current download is never used to supply historical terms or a legal effective date. No public full-document fixture is added and no existing evidence is overwritten.

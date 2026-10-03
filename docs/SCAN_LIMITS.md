# Resource bounds and incomplete plans

## Payload bytes

There is no default per-project or opaque-resource byte ceiling. File hashing, copying, ZIP writing,
verification and extraction use 1 MiB reads. Small-file caching is limited to 32 MiB per inventory.
Large content checks use overlapping 64 KiB windows; ambiguous overlong recognizer context blocks
instead of being silently discarded. These recognizers are not a complete DLP system.

Code, Notebooks and structured documents still require a complete bounded parse (16 MiB per file).
An oversized document produces `parser-file-limit`; it is never approved by examining only a prefix.
Large opaque required resources can be retained and hashed without parsing their whole content.
Optional policy `max_file_bytes` and `max_scan_bytes` impose operator-selected byte budgets;
both default to null. Read reservations include one growth-detection byte and are not refunded.

Build and extraction check current free disk space. Private staging reservations use actual selected
sizes plus archive/evidence overhead, with no former 640 MiB staging or 1 GiB total-state cap.
Archive verification first takes a temporary disk-backed snapshot, shared by extraction/runtime.
Allow space for the source copy, archive, immutable verification copy and extracted runtime files.
Free-space estimates cannot prevent another process filling the disk; write failures are failures.

## Independent safety and evidence limits

- 20,000 observed directory entries globally, including errors and rejected entries
- 4,096 entries in one directory; 64 directory levels
- 1,000 ordinary inventory error details plus a terminal diagnostic
- 20,000 analysis evidence charges across findings, references/imports and blocker details
- ZIP central-directory metadata 64 MiB; release manifest 16 MiB
- ZIP entries support STORE/DEFLATE, reject encryption, links and expansion ratios above 1,000
- Public HTTP request bodies remain limited to 64 KiB; these are not project payload uploads

ZIP64 is supported by archive writing and verification. This does not mean source analysis promises
more than its entry bound. Format-scale tests and full-project tests are reported separately.
Directory enumeration is bounded before sorting, with one lookahead to detect overflow. A directory
overflow stops globally instead of choosing an arbitrary enumeration prefix. Incomplete scans are
BLOCKED; their hashes and counters cover only the explicitly recorded scope. They cannot build.

Private history retains up to 20 eligible full audits (64 MiB total) and 100 summaries. Per-audit,
journal, inspection and owner-registration bounds still protect metadata handling; see [desktop
storage](DESKTOP.md#storage-and-history). Unknown or changed content is retained for review.

These bounds are not a hostile-code sandbox or a wall-clock guarantee. Slow disks, parsing and
pattern matching depend on input. Cancellation is checked between chunks; blocking OS calls can
delay it. Explicit target execution uses separate timeouts and isolation controls.

## Read the result correctly

`plan` prints grouped summaries; `--details` prints private full evidence. A blocked scan returns 2,
a static candidate returns 3, and the appropriate completed gate returns 0. Fewer retained blockers
after a limit do not mean problems were fixed. Select a coherent component using real dependencies
and reviewed requirements, never modification time alone. No policy can approve a detected secret.

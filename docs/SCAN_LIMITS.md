# Scan limits and diagnostic interpretation

## Deterministic limits

- 20,000 observed directory entries globally, including unreadable and rejected entries
- 4,096 entries in one directory
- 256 MiB of read reservations; each attempted regular-file read reserves its observed size plus one mutation-detection byte
- 1,000 ordinary inventory error details, plus a terminal limit diagnostic
- 64 directory levels
- 20,000 analysis evidence charges across findings, references/imports and blocker details

One enumeration lookahead entry may detect overflow. Directory enumeration is bounded before sorting;
an overflowing directory is not partially processed in filesystem enumeration order. Read reservations
are not refunded when a read fails. Reservation counters describe a conservative bound, not measured
I/O for failed reads. The per-file policy limit remains separate (16 MiB by default).

Limits stop globally and mark the plan incomplete. Successful files retained before a stop are hashed,
but that identity covers only the stated scope, not an unvisited whole project. No incomplete plan can
build a release. Detailed counts are retained-evidence counts, not estimates of unknown omissions.

These are source-analysis and evidence bounds, not a hostile-code execution sandbox or a promise of
constant wall-clock latency. Slow filesystems, parsing and pattern matching still depend on the input.
Target execution uses its separate timeout and isolation controls.

## Large workspaces

A development directory may contain multiple historical projects, data archives and environments.
A safe stop is preferable to silently calling its first subset a complete release. Select a coherent
component using actual entry points, dependencies and accepted version evidence. Do not pick the
newest timestamp alone, and do not delete core capabilities to fit a limit.

The default engine cannot know approvals stored only in a private conversation. Supply a reviewed
project policy or an explicitly selected source root when that information is required. Such a run is
configured assistance, not an unassisted-default benchmark. Preserve the original default outcome when
comparing results, and evaluate manually curated packages with the same functional and safety checks.

## CLI compatibility

The plan command prints grouped summaries for `plan`. Full plans continue to be written to the specified
work directory. Use `--details` when full stdout is needed; handle it as potentially private evidence.
The statuses and exit codes are unchanged: a blocked scan returns 2, a static candidate returns 3,
and only the appropriate completed gate returns 0.

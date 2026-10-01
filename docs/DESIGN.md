# Design and threat boundaries

Releasecraft prepares **source releases**, not compressed context for a language model.
The deterministic core uses only Python's standard library. It performs no model calls,
telemetry, credential discovery, repository upload, or remote publication.

## Decision order

1. Reject unsafe paths, links/reparse points, hard links, unreadable or oversized files.
2. Preserve license obligations and flag third-party provenance requiring review.
3. Exclude private environment files and known caches/transient extensions.
4. Apply explicit exclusions, external declarations, and inclusions.
5. Preserve source, tests, documentation and native build metadata conservatively.
6. Promote referenced resources; unresolved resources and dynamic reads block the plan.
7. Strip Notebook outputs when configured, then scan public bytes again.
8. Safety findings override ordinary inclusion. Excluded dependencies block publication.

Versioned policy and hashes freeze decisions. The program does not decide that an old
implementation is obsolete merely because of its age or filename. Explicit policy may
exclude it; dependency checks then prevent silently omitting known references. Git ignore
files do not determine publication membership. Files unknown to Git are considered normally.

## Supported analysis

Python imports, literal dynamic imports, literal file reads, selected subprocess script
references; Node/TypeScript literal imports and file reads; local Markdown/HTML/CSS resource
links; Notebook code cells; JSON and TOML syntax; explicit dynamic resource declarations.
Source mode preserves regression tests by default. Runtime mode excludes ordinary tests/docs
but still applies dependency gates. Research mode conservatively retains the source set;
scientific assets require explicit resource decisions. It does not certify scientific claims.

Dynamic expressions, environment-dependent plugins, aliases, binary models, custom bundlers,
external data, and unclear third-party rights must be resolved explicitly. A reviewed-dynamic
entry records why a site's inputs are external/user-supplied; it never clears security findings.
There is no universal dependency theorem or legal clearance. Project authors remain responsible
for rights, data privacy, and meaningful validation commands.

## State machine

UNSUPPORTED: no supported project family. BLOCKED: unresolved dependency, policy, license,
or safety condition. PLANNED: frozen analysis can build. CANDIDATE: exact ZIP passes structural,
integrity, and built-in secret checks; runtime validation has not passed. READY: declared
commands and claim coverage passed on that exact archive, with backend/isolation in the report.
FAILED: validation failed. Exit 0 is reserved for PLANNED, READY, and informational operations;
CANDIDATE exits 3 and blocking/failure states exit 2.

READY is scoped to declared commands and detector coverage, not a promise of universal
correctness or absence of every possible secret. Reports must travel with the ZIP hash.

## Execution boundary

Default runtime validation requires Docker and an already-installed digest-pinned image.
There is no implicit image pull or network access. Containers run as an unprivileged user,
with dropped capabilities, no-new-privileges, resource limits, a read-only root filesystem,
and only an extracted release mounted read-only. Each command gets a fresh disposable copy;
make an install-and-test workflow a single command when state must persist between steps.
Host homes, credential mounts, SSH agents and original project directories are not mounted.

The explicit trusted backend is for code already reviewed and trusted by its operator.
It creates a fresh Python virtual environment without system site packages, sanitizes inherited environment variables, uses a different extraction path and bounded
execution, but **is not a security sandbox**. Never use it to execute an unfamiliar repository.
Virtual environments are dependency isolation, not hostile-code containment. If Docker is
unavailable, untrusted commands stay BLOCKED. A hostile program with container/kernel exploits
still requires stronger isolation such as a disposable VM.

## Determinism and recovery

Sorted ZIP entries, fixed 1980 timestamps, normalized executable modes and ZIP_STORED avoid
compressor/version-dependent output. JSON uses stable key ordering. Release manifests list
content hashes without attempting to hash themselves. The ZIP SHA-256 is a separate sidecar.
Plan files and absolute source paths belong only in the external private work directory.
Repeated runs use fresh output destinations. Interrupted builds leave no successful output;
a frozen plan may be replayed if the complete input snapshot is unchanged.

The scan is bounded to 20,000 considered entries, 256 MiB total and a configurable per-file
limit (16 MiB by default). Known cache directories are recorded as excluded directory entries
without traversing their contents. File identity is checked around reads and the entire
snapshot is rechecked before publication. POSIX reads use no-follow directory descriptors.
On Windows, file reads hold ancestor handles without delete/write sharing and reject reparse points before reading. Process timeouts use a Job Object assigned before the suspended target resumes. Native Windows testing is reported separately. Freeze the input during analysis.

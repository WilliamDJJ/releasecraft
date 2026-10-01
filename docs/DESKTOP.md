# Desktop workflow

[English overview](../README.md) · [中文说明](../README.zh-CN.md) · [Policy](POLICY.md)

## Prepare a source candidate

On Windows, double-click `Start Releasecraft.cmd` in the extracted platform bundle. The first
window installs its verified bundled wheel offline in a new local `.venv`; an existing environment
is never overwritten. Python 3.11+ with Tcl/Tk must already be available. On Linux, install the
matching Python venv/Tk prerequisites, run `sh install.sh`, then `sh releasecraft-gui.sh` in a
graphical session. Installed source/wheel users can run `releasecraft-gui` or `releasecraft gui`.

Choose a project root with a README and license, review the scope, and select Prepare package.
The native chooser and path fields accept spaces and Unicode. Common scope switches cover tests,
documentation, notebooks, sample data and reproducibility assets. Advanced options expose the
selection profile, Notebook output stripping, an explicit policy and excludes. Required resources,
license gates and detected secrets remain mandatory checks. Runtime mode is a selection profile,
not proof that the package can execute.

## Language and progress

The visible English / 中文 selector changes controls, help, phases, errors and summaries using
shared translations. Switching during work preserves the current operation, paths and decisions.
Raw diagnostic identifiers and exact input paths are not translated; displayed sensitive values
are redacted. The last language is stored in `desktop-preferences.json` under the user state
directory, never in the selected project or public archive.

Scanning shows observed files and bytes with an unknown total until a total is known. Later
phases show their own measured counters; elapsed time is wall time. The bar is indeterminate
where no honest percentage exists. Cancel stops at the next safe checkpoint; an individual
bounded read or filesystem operation may finish first. A completed commit cannot be cancelled
retroactively. No target-project command is run by this window.

## Owned output and private state

The default location is the selected project's direct `releasecraft-output` child. An external
location must be a dedicated directory with that same name and disjoint from the project.
Preexisting unregistered directories are refused. A public marker plus a private registration
bind the output to the actual project and output directory identities; copying a marker does
not authorize pruning. Verified owned output is excluded from later scans. Removing the private
registration makes an old output unrecognized; it is not silently adopted or deleted.

Each run uses a fresh `release-<identifier>` child. Successful public output contains only
`release.zip`, its checksum and a static `CHECKS.json`. Full plans and raw problem evidence are retained under the limits below.
Temporary staging is removed only after exact ownership verification. The private state directory is `%LOCALAPPDATA%/Releasecraft` on Windows,
or `$XDG_STATE_HOME/Releasecraft` (default `~/.local/state/Releasecraft`) on Linux. Paths and
project details in private plans can be sensitive. Do not publish this state directory.

Directory handles, no-follow reads, exclusive creation, ownership checks, an OS-released lease
and identity/content verification protect against links, substitution, overlap and accidental
overwrite. Repeated runs create new children; simultaneous prepare or storage-maintenance operations in one user state directory are
refused using an OS-released global lease. Cancellation removes only known newly created files with matching identities and empty
owned staging directories. Unexpected content is retained with private cleanup evidence.

The source content must remain stable through analysis and publication. These checks are not
a sandbox against another process with the same user's authority, nor a filesystem transaction
over arbitrary concurrent edits. A late verification failure is FAILED and any uncertain output
is retained for review, never reported as a verified success.

## Understand the result

BLOCKED means a dependency, secret, license, unsupported decision or scan limit needs attention.
Details retain stable codes and show translated next steps. Scope checkboxes cannot approve
secrets or remove required inputs. Safe configuration templates use placeholders such as
`${API_KEY}`; actual keys, passwords and private keys belong outside selected release content.

CANDIDATE means the actual archive passed static checks. Open output locates it in the file
manager. READY is reserved for separate explicit command/claim runtime validation via the CLI.
The default workflow cannot infer execution order between unrelated build/check scripts or
recover approvals stored in private conversation history.

## Storage and history

Storage / History shows measured private bytes, retained audit jobs and cleanup results. Export
selected audits before clearing details. Exports are private evidence, preserve exact registered
audit bytes, and never overwrite a file. Public packages and original projects are outside these
cleanup controls. The language selector also updates the storage window during a running task.

Unchanged staging files are removed after success, cancellation or failure using creation-time
identities and content hashes. Unknown, replaced, linked or incompletely journaled content is
retained with a warning. A verified public CANDIDATE and an incomplete cleanup can coexist;
cleanup does not upgrade a candidate to READY. Historical unregistered state is never adopted.

Automatic retention keeps at most 20 eligible full audits within 64 MiB total and at most 100
compact summaries. Each full audit is limited to 16 MiB (the plan itself to 8 MiB to leave room
for result evidence). Audits that cannot be safely verified are retained, counted against private
capacity and may block new work; count limits never authorize deleting unknown content.

Admission allows at most 1 GiB of measured private state plus the current reservation. Staging
reservations use selected sizes, conservative notebook expansion and archive overhead, capped
at 640 MiB; actual writes are also bounded. Inspection is limited to 50,000 entries and 72
directory levels, journals to 12 MiB per job, and output registrations to 256. Registrations
are not silently forgotten to make space. Slow storage still affects elapsed time. Disk free
space is an advisory check, not a guarantee against other applications filling the disk.

STORAGE_BLOCKED means safe ownership, capacity or evidence bounds could not be established.
Use the storage panel to export evidence and clean eligible staging or expired audits. Clear
full audits is an explicit action with confirmation. Active work cannot be cleared. A crash
releases the OS lease; only finalized, unchanged journal entries are eligible for recovery.
Files created before an interrupted journal update stay for review. There is no automatic
recursive deletion of discovered directories and no automatic removal of public releases.

## Linux filesystem requirement

Atomic output publication requires a Linux filesystem supporting the no-overwrite
`renameat2` operation. Native Linux filesystem output was tested under WSLg. In the
tested WSL environment, output on the Windows-mounted filesystem returned `EINVAL`;
the operation failed without reporting a successful package. Use a native Linux
output location, or the Windows bundle when working directly on Windows folders.
Other mounted or network filesystems are not covered by this validation.

<p align="center"><img src="docs/assets/banner.svg" alt="Releasecraft — From working directory to verified release" width="100%"></p>
<p align="center"><strong>Keep what matters. Explain every decision. Verify the release.</strong></p>
<p align="center"><a href="CHANGELOG.md"><img src="docs/assets/version.svg" alt="Version 1.0.0"></a> <a href="#quick-start"><img src="docs/assets/python.svg" alt="Python 3.11+"></a> <a href="LICENSE"><img src="docs/assets/license.svg" alt="MIT license"></a> <a href="docs/DESIGN.md"><img src="docs/assets/local.svg" alt="Local analysis"></a></p>
<p align="center"><strong>English</strong> · <a href="README.zh-CN.md">简体中文</a><br><a href="#why-releasecraft">Why Releasecraft?</a> · <a href="docs/DOWNLOADS.md">Downloads</a> · <a href="#quick-start">Quick start</a> · <a href="docs/POLICY.md">Configuration</a> · <a href="docs/VERIFICATION.md">Verification</a></p>

## Turn a messy project into a release you can inspect

Releasecraft prepares clean, reproducible open-source **source releases** from working directories.
It identifies code and resource relationships, records what to keep and why, builds a separate
release copy, and checks the actual archive. A compact native desktop window, local HTTP interface and CLI share the same deterministic engine.
Original source files stay unchanged; the desktop workflow adds a separately owned output directory.

**For Python research, Notebooks, data-processing projects, and conventional Node.js/TypeScript repositories.** No model API key, paid account, or remote analysis service is required.

## Why Releasecraft?

- **Beyond filename filters.** Keep required JSON, templates, package data and tests using detected references and explicit policy
- **Decisions you can audit.** Every considered file has a decision and evidence; unresolved dependencies, secrets or rights block release
- **Repeatable output.** Freeze the input and decisions, rebuild stable archives, and compare SHA-256 checksums
- **Verification after packaging.** Validate an extracted archive rather than quietly borrowing files from the development directory
- **One core, convenient entry points.** Use the bilingual desktop window, CLI or token-protected localhost interface; analysis stays local

**Analyze → review the plan → build a clean copy → validate the archive**

A smaller archive is useful only if the declared functionality, maintenance files and license obligations survive.

## Downloads

Download **v1.0 (package 1.0.0)** from the [official GitHub release](https://github.com/WilliamDJJ/releasecraft/releases/tag/v1.0).
The [source repository](https://github.com/WilliamDJJ/releasecraft) contains the same shared codebase used by all distributions:

| Package | Intended use | Requirements |
| --- | --- | --- |
| [Windows ZIP](docs/DOWNLOADS.md#windows) | Double-click installation and desktop window | Windows, Python 3.11+ with pip/venv and Tk |
| [Linux tar.gz](docs/DOWNLOADS.md#linux) | Local installation with shell launchers | Linux, Python 3.11+ with pip/venv and Tk |
| [Source ZIP / universal wheel](docs/DOWNLOADS.md#source-and-wheel) | Development, source review, custom installation | Python 3.11+ |

The platform bundles include the same Python wheel and install it offline into a local `.venv`.
They are **not standalone executables** and do not bundle Python. See the [download guide](docs/DOWNLOADS.md) for publication status, exact asset names and checksums.

## Quick start

### Windows bundle

Extract the Windows ZIP and double-click **Start Releasecraft.cmd** inside its `releasecraft`
folder. The first-launch window installs the bundled wheel offline into a new local `.venv`.
Python 3.11+ with Tcl/Tk must already be installed. Existing environments are never overwritten.

1. Choose **English / 中文** in the visible language selector
2. Browse to a coherent project root containing its README and license
3. Keep the default source scope, then click **Prepare package**
4. Review any blockers; when a candidate is built, click **Open output**

The default destination is `releasecraft-output` inside that project. Only an output registered
by this application for that exact project is omitted from later scans. An existing unregistered
directory is refused. Every successful run gets a fresh child directory; private plans remain
outside the project. An external dedicated output directory is available. See [desktop workflow](docs/DESKTOP.md).

### Linux bundle

With Python 3.11+, venv and the matching Tk package installed, extract the Linux tar.gz and run:

```sh
sh install.sh
sh releasecraft-gui.sh
```

A graphical desktop session is required for the native window. For command-line use, run
`sh releasecraft.sh --help`. The optional HTTP interface remains available through
`releasecraft serve --source /path/to/project --work /path/to/separate-work`.

The desktop workflow creates a **CANDIDATE**, never executes selected project code, and never
labels an untested package READY. Runtime validation is a separate explicit CLI operation.

### Install from source

From the repository root:

```sh
# Linux
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/releasecraft --version
```

```powershell
# Windows
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install .
.\.venv\Scripts\releasecraft.exe --version
```

Source installation needs setuptools 68+; pip may fetch build dependencies. The bundled-wheel
installers require no network. No administrator access or PowerShell execution-policy change is needed.
Linux distributions may package `venv` separately. Install the matching Python venv package if required.

## Try a complete release

The included trusted demo reads a required JSON resource and checks its result.
The following uses `releasecraft` after adding the installed executable directory to PATH.
Alternatively replace it with `.\releasecraft.cmd` on Windows, `sh releasecraft.sh` on Linux,
or the explicit source-install executable above.

```sh
releasecraft plan examples/demo --config examples/demo-policy.json --work ../demo-work
releasecraft build examples/demo --plan ../demo-work/plan.json --output ../demo-release
releasecraft verify ../demo-release/release.zip
releasecraft validate ../demo-release/release.zip --backend trusted --trust-project --report ../demo-validation.json
```

`build` and static `verify` return **exit code 3 (CANDIDATE)**. Runtime validation of the demo
returns **0 (READY)**. Do not treat CANDIDATE as completed validation or hide a nonzero exit code.
Use fresh work/output directories when repeating this example.

| Output | Purpose |
| --- | --- |
| `source/` | Clean source tree with a machine-readable release manifest |
| `release.zip` | Stable archive containing the selected files |
| `release.zip.sha256` | External archive checksum |
| `validation.json` | Static validation report bound to the archive hash |

The trusted backend uses a fresh Python environment, **not a security sandbox**. Use it only for
reviewed code you trust. Untrusted projects require the default Docker backend and a preinstalled,
digest-pinned image supplied with `--image`. Missing isolation produces BLOCKED without executing code.
Docker commands have no network access; Releasecraft never pulls images automatically.

## Configure, inspect and replay

```sh
releasecraft analyze /path/to/project --config /path/to/release-policy.json
releasecraft diff old-plan.json new-plan.json
```

Files receive INCLUDE, EXCLUDE, TRANSFORM, EXTERNAL or UNRESOLVED decisions. Source, tests,
licenses and documentation are retained conservatively. Unknown data is not silently discarded;
explicit excludes cannot silently remove a known dependency. Freeze reviewed policy rather than
manually modifying hashes. Keep the source unchanged throughout analysis and building.

- [Desktop workflow](docs/DESKTOP.md): language, scope, output ownership, progress and cancellation
- [Policy reference](docs/POLICY.md): includes/excludes, resource declarations, validation commands and claims
- [Design boundaries](docs/DESIGN.md): supported analysis and safety decisions
- [Validation guide](docs/VERIFICATION.md): claim-to-test mapping and acceptance commands
- [Release guide](docs/RELEASING.md): one repository, versioned assets and publication steps
- [Changelog](CHANGELOG.md): changes between versions

## Start with defaults

For a coherent project with its own README and license, start without a policy file:

```sh
releasecraft plan /path/to/project --work /path/to/new-work
releasecraft build /path/to/project --plan /path/to/new-work/plan.json --output /path/to/new-release
```

Build only after `plan` reports PLANNED. Literal package resources, selected native packaging
declarations and module-relative Node assets can establish required files automatically.
Unknown data, dynamic plugin choices and unclear licensing still need review. Source mode retains
maintenance files; runtime mode is a separate selection profile, not proof of an installable wheel.
See [default resource analysis](docs/DEFAULTS.md) for supported forms and limits.

Literal `.npmrc` build/package preferences are supported through a bounded static subset.
Credentials, environment references and machine-specific settings remain blocked; see
[default analysis](docs/DEFAULTS.md#literal-npm-preferences).

## Understand a blocked plan

`plan` prints a compact, path-free summary grouped by blocker code and next action. The full
private evidence remains in the work directory's `plan.json`; add `--details` to print the full JSON.
Automation should read `plan.json` or use `--details`.

A scan that reaches an entry, byte, directory, depth or evidence limit is **incomplete and BLOCKED**.
Retained counts are not totals for the unvisited project. Choose a coherent component root; do not
interpret fewer reported blockers as resolved problems. Modification times are not release approval,
and Releasecraft does not infer a person's accepted final version from private conversation history.
See [scan limits](docs/SCAN_LIMITS.md).

## Test and build

```sh
python -m unittest discover -s tests -v
python scripts/build_distributions.py --output ../releasecraft-artifacts
```

Run with the environment that has Releasecraft installed. Distribution building additionally
requires setuptools 68+ and wheel in that environment. Node.js is required for Node execution
and frontend-script tests. Skips remain skips, not passed tests. The build command prepares
candidate assets; it does not publish them or declare runtime acceptance complete.

Stable Python import aliases, literal CommonJS directory-relative resources and a bounded immediate
create-then-read pattern are recognized. Conditional or dynamic cases still need review. See the
[documented static subset](docs/DEFAULTS.md); a static candidate is not runtime acceptance.

## Scope and safety

Supported analysis covers conventional Python/Notebook and Node/TypeScript structures, literal
imports/resources and selected native packaging declarations. Dynamic resources need explicit
reviewed policy. Scientific results and business logic are never rewritten to make a build pass.
Notebook output stripping is the bounded automatic transform; research mode preserves outputs
unless explicitly configured. Missing README generation uses only declared metadata and claims.

Known-pattern scanning is not a complete secret audit, legal opinion or license-clearance service.
Git history, every encoding and arbitrary nested archive formats are outside its scope. Large or
unreadable files, unclear licenses and unresolved external resources block release. Private data
must not be published solely because a regex scan passed. Optional model enhancement is not implemented.

Windows/Linux are the distribution targets; the accompanying hash-bound validation report records
what was actually tested. Docker, GPU, databases, commercial datasets and macOS require their own
acceptance evidence. An optional `--wheelhouse PATH` supplies explicitly hashed offline dependencies
for runtime validation without relying on host packages or hidden caches.

## License

[MIT](LICENSE). Input-project licenses are preserved, never replaced with Releasecraft's license.
See [design references](docs/RESEARCH.md) for component research and attribution boundaries.

The desktop **Storage / History** panel measures private usage, exports audits and cleans only
verified owned staging. Full audits expire under explicit limits; unknown or active content is
retained and may block new work. See [storage and history](docs/DESKTOP.md#storage-and-history).

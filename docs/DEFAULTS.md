# Default resource analysis

[Overview](../README.md) · [Policy](POLICY.md) · [Scan limits](SCAN_LIMITS.md)

Default analysis needs no model, network service or project execution. A complete plan requires
a recognizable license, source/documentation and resolved required resources. Unknown files are
reported for review rather than silently discarded. A source archive and a runtime package have
different purposes; native package declarations add evidence without replacing source maintenance.

## Concrete resource evidence

- Existing literal Python reads, file-relative pathlib expressions and literal imports
- Imported `importlib.resources.files("package")` followed by literal `joinpath` or `/` components
  and `read_text`, `read_bytes` or `open`; ordinary import aliases are recognized
- Setuptools `package-data`, literal `package-dir`, `packages.find.where`, `data-files`, and
  project/setuptools `license-files` declarations in `pyproject.toml`
- Selected `MANIFEST.in` include, recursive-include and graft declarations
- Node package file/entry declarations and literal `readFile`/`readFileSync` calls using
  `new URL("./asset.dat", import.meta.url)`; URLs resolve relative to their module

Package-resource anchors currently require one unambiguous local package with `__init__.py`.
Variable anchors, reassigned or shadowed imports, namespace-only packages and arbitrary runtime
dataflow require explicit evidence. Escaped JavaScript URL strings and other URL bases remain
conservative. JavaScript analysis is a bounded recognizer, not a complete JavaScript parser.

Packaging globs match path components. `*` does not implicitly match nested directories or hidden
names; `**` expresses recursion. Metadata declarations cannot bypass detected secrets, third-party
provenance, explicit exclusions or a missing required resource. A concrete read/declaration can
promote a binary resource; merely mentioning a path cannot. Known-pattern scanning does not certify
the absence of all private data in a binary file.

`include-package-data` does not mean “publish every unclassified file.” Releasecraft uses explicit
manifest/resource evidence and does not treat Git tracking or ignore rules as publication approval.
Backend plugins, dynamic build configuration and full native packaging semantics are outside these
static rules. Validate the produced package with the project's actual declared workflows.

## Maintenance and outputs

Source mode retains tests, documentation and `.github/workflows/*.yml` / `*.yaml`; runtime mode
omits workflow maintenance files. Required ignored or untracked resources remain eligible for
inclusion. Existing deterministic cache pruning and transient-file rules remain in effect.
Scientific results, checkpoints and arbitrary JSON files are not automatically labeled junk.
Literal creation/write operations do not establish a missing input; unknown modes remain blocked.

## Literal npm preferences

Project `.npmrc` files at any directory level are retained when every setting is in this literal
subset. File-name matching is case-insensitive for portable inspection; npm's own file discovery
still depends on the host. Supported lowercase keys are:

- Boolean `true` or `false`: `package-lock`, `package-lock-only`, `format-package-lock`, `save-exact`,
  `fund`, `progress`, `color`, `unicode`, `engine-strict`, and `prefer-dedupe`
- `lockfile-version`: literal `1`, `2`, or `3`

Blank lines, spaces/tabs around `=`, LF/CRLF endings and plain full-line `#`/`;` comments are
accepted. Files are bounded to 64 KiB and 256 physical lines. Comments containing assignments,
URLs or environment substitutions require review; all comments still undergo sensitive-content
scanning. Empty configuration is a supported no-op.

Unknown keys, duplicate keys, sections, arrays, quotes, inline comments, nonliteral values,
environment references and path/registry/execution settings remain `npm-config-needs-review`.
No variables are expanded and no npm command is executed. An include/resource declaration cannot
override this check. Credential assignments are scanned independently, including recognized npm
auth-key variants in other file types. This remains known-pattern detection, not a guarantee that
all private information can be recognized. Explicitly excluded config is not published.

The same config gate is applied when verifying an archive. These rules select source files;
they do not claim to reproduce npm's complete INI parser or runtime package contents.

## Literal aliases, generated files and maintenance

Imported aliases of `importlib.import_module` retain literal local-module dependencies. Unknown
module names and shadowed aliases still require review. CommonJS reads through a stable
`require("node:path")` or `require("path")` binding and `join(__dirname, "literal", ...)` are
file-relative. Computed components, escapes, reassignment and unsupported binding forms remain
dynamic. Relative JavaScript imports resolve from their importing file, without a project-root
fallback; directory-index lookup also handles `require("./")`.

A missing file is recognized as generated only in a narrow Python pattern: an unconditional
top-level `with open(literal, write_mode)` followed immediately by an expression, assignment or
assertion reading that same literal. The writer body permits direct stream writes or standard
`json.dump`; reader calls are restricted to builtin `open` and standard JSON readers. Shadowed
APIs, conditionals, intervening operations and lazy/function bodies are not inferred. Existing
source files still undergo normal inclusion, exclusion and secret checks. This is not general
runtime dataflow analysis and does not replace runtime validation.

Source profiles retain `.travis.yml`/`.travis.yaml`, `.eslintrc.json` and `tox.ini` as maintenance
files; runtime profiles omit them unless explicitly included or required. JSON syntax and all
ordinary sensitive-content checks still apply. Other unknown configuration remains unresolved.
Conventional repository-relative issue, pull-request and discussion links are website navigation,
not bundled input files. Arbitrary links outside the source tree are not silently accepted.
Markdown fenced code examples do not create document dependencies. Real links and HTML assets
outside those fences still require their files; sensitive-content checks scan the entire document.
GitHub funding metadata is retained in source mode alongside conventional lint/CI/test configuration;
runtime mode omits it. Other unknown GitHub configuration still requires a decision.

Notebook output stripping preserves metadata and source attachments because they may control
execution or presentation. A sensitive value in retained metadata remains a release blocker.

## Review and replay

A Python path may also be a string assigned once at module level before its use. Reassignment,
conditional assignment, imports or parameter shadowing leave it unresolved. This is a literal
binding rule, not general Python evaluation or runtime dataflow analysis.

Read the grouped plan summary first. Detailed private evidence remains in `plan.json`; `--details`
prints it. If a required input is genuinely absent, restore it. If a dynamic choice is unresolved,
declare a bounded resource set or reviewed evidence. Never remove a license/secret blocker merely
to obtain a smaller archive. Freeze the chosen policy, keep inputs unchanged and compare repeat
archive hashes. Runtime validation is a separate, explicit gate.

These rules do not identify a person's privately approved final version or replace a project owner.
Scan and evidence limits are unchanged; an incomplete scan is always blocked.

## Reference semantics

- [Setuptools data files](https://setuptools.pypa.io/en/stable/userguide/datafiles.html)
- [Setuptools distribution files](https://setuptools.pypa.io/en/latest/userguide/miscellaneous.html)
- [npm configuration files](https://docs.npmjs.com/cli/v11/configuring-npm/npmrc/)
- [npm configuration options](https://docs.npmjs.com/cli/v11/using-npm/config/)

Releasecraft interprets a documented static subset; it does not execute or reproduce an entire build backend.

## Python expression and local-function boundaries

Unquoted credential-assignment checks distinguish proven parameter references and direct environment
lookups from literal values in parsed Python source. Defaults, unknown/shadowed bindings and config
files remain conservative. All raw token, private-key, credential URL and literal-value scans remain
active. This is a bounded recognizer, not a general dataflow or secret-discovery guarantee.

Unambiguous local module-level functions named like readers are analyzed at their definitions.
Actual reads inside them remain dependencies. Decorated functions, reexports and shadowed bindings
do not establish a plain local function identity. Aliased library readers retain required inputs.
Execution order across unrelated commands is not inferred; a generated-file checker may need an
explicit reviewed workflow. A missing input is never waived merely because another file can write it.

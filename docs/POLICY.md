# Policy reference (schema 1, policy 1.0)

Policies are explicit JSON files passed with `--config`. A policy in an input repository is
never automatically loaded. Review its commands before any execution. Unknown fields are
errors. Glob matching is case-sensitive against slash-separated relative paths; `dir/**`
selects descendants. Absolute, traversal and Windows-reserved paths are rejected.

| Field | Meaning |
|---|---|
| schema | Must be 1 |
| mode | source (default), runtime, or research |
| include | Explicit inclusion globs; cannot override safety gates |
| exclude | Explicit exclusion globs; referenced exclusions block release |
| resources | Exact required resource paths; missing paths block release |
| dynamic_resources | Source path to a list of exact runtime resources |
| reviewed_dynamic | Source path to an object with a nonempty reason for reviewed dynamic I/O |
| external | Resource path to reason, instructions and expected sha256; remains BLOCKED pending external validation |
| third_party | Path to reason, source URL and license identifier; record only verified rights |
| notebook_outputs | strip (source/runtime default) or preserve (research default); both remain subject to content scanning |
| max_file_bytes | Per-file bound, default 16777216; range 1024–134217728 |
| commands | Objects containing unique id, argv string array, optional timeout (1–600 seconds) |
| claims | Objects containing description and a nonempty commands array of command IDs |

Example:

```json
{
  "schema": 1,
  "mode": "source",
  "exclude": ["scratch/**", "tests/one_off_check.py"],
  "resources": ["assets/weights.bin"],
  "dynamic_resources": {"app.py": ["assets/weights.bin"]},
  "commands": [{"id": "regression", "argv": ["python", "-m", "unittest", "discover", "-s", "tests"], "timeout": 120}],
  "claims": [{"description": "Load the bundled model and preserve regression behavior", "commands": ["regression"]}]
}
```

A reviewed_dynamic reason acknowledges an investigation, not automatic proof. Use it only for
actual external inputs or verified bounded behavior; prefer exact dynamic_resources for bundled
assets. Tests should exercise these sites. No field suppresses secret detection or permits links.
Research data and model rights require review independent of filename or file size.

Plans are private evidence: paths, excluded filenames and reasons may be sensitive. Keep them
outside the published repository. The public manifest contains only selected relative paths,
hashes, transformations and declared validation commands. Commands and claims are scanned
before they can enter the public manifest.

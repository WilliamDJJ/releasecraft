# Releasing Releasecraft

[Overview](../README.md) · [Downloads](DOWNLOADS.md) · [Changelog](../CHANGELOG.md)

## One repository, multiple assets

The official repository is [WilliamDJJ/releasecraft](https://github.com/WilliamDJJ/releasecraft).
Both operating-system bundles contain the wheel built from the same frozen source release. Do not maintain separate Windows and Linux source branches.

The GitHub repository root is the content of the source ZIP, not a folder containing old archives.
Keep account records, working plans and private test logs outside it. Release assets belong to the
GitHub Release, not the source tree. No script here pushes code or publishes a Release automatically.

## Version updates

1. Update the version in `pyproject.toml` and `src/releasecraft/__init__.py`
2. Update both READMEs, `CHANGELOG.md`, the local version badge and `DOWNLOADS.md`
3. Run the full tests with Python and Node available; inspect skips separately
4. Build candidates from an installed development environment with setuptools 68+ and wheel:

```sh
python scripts/build_distributions.py --output ../releasecraft-artifacts
```

The output path must be new and outside the source tree. The build creates:

- `releasecraft-<version>-source.zip`
- `releasecraft-<version>-windows.zip`
- `releasecraft-<version>-linux.tar.gz`
- `releasecraft-<version>-py3-none-any.whl`
- `SHA256SUMS`

`work/` and `self-release/` contain local analysis and staging evidence. They are not public
release assets. The source ZIP is built by Releasecraft itself. Distribution manifests record
its hash and the exact bundled files. Fixed archive order, timestamps, modes and gzip headers
make artifacts repeatable with a fixed build toolchain; verify byte equality rather than assume it.

## Acceptance gate

Extract the source archive to a new path and install noneditable into a clean virtual environment.
Run the full tests and documented demo workflow there. Separately extract each platform bundle
on that actual platform, run its installer and launcher, validate the demo, and exercise the local
HTTP interface and native desktop window in both English and Chinese. Verify the language preference, active-operation switching, cancellation, source-contained output ownership and first-launch offline installer. Include paths containing spaces and Unicode. Repeat the build and compare hashes.

Do not label a release accepted if a required platform is blocked or tests fail. Record actual
platforms, Python/build-tool versions, pass/fail/skip counts and external limits in a separate
report bound to the final artifacts' hashes. Any later code or documentation edit invalidates
those hashes and requires rebuilding and affected revalidation.

## Re-run platform acceptance

Run on the actual target OS from an environment with Releasecraft installed:

```sh
python scripts/check_distribution.py --archive ../releasecraft-artifacts/releasecraft-1.0.0-linux.tar.gz --trust-distribution
```

On Windows, pass `releasecraft-1.0.0-windows.zip` instead. The check installs the bundled wheel
offline and executes the demo in a disposable directory. It intentionally requires trust and is
not a sandbox for third-party software. Full source tests and launcher/UI checks are separate gates.

## Manual publication

Only after acceptance and explicit authorization to publish:

1. Verify the official owner/repository and push only the reviewed source root with a private commit email
2. Prepare versioned asset links in the release revision; verify them after uploading the corresponding assets
3. Create tag `v1.0` for the exact accepted source revision
4. Create a GitHub Release for that tag and attach the five public build outputs above plus the validation report
5. Verify the public release, every download hash, both README links and the actual CI result for the tagged commit

Changing documentation changes source content: include it in a newly accepted build before
publishing that revision. Do not add fabricated download counts, CI success badges or test claims.
The [Tests workflow](https://github.com/WilliamDJJ/releasecraft/actions/workflows/tests.yml) records
actual runs; configuration alone is not evidence of a passing run. Standard hosted runners are
used for this public repository; do not switch to paid runners as part of release automation.

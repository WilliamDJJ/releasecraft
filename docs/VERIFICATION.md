# Verification contracts

The delivered external report binds results to the final ZIP SHA-256. This document defines
test intent; it does not substitute for execution evidence.

| Claim | Test evidence |
|---|---|
| Required JSON retained, unrelated JSON requires a decision | test_required_json_promoted, test_unknown_json_blocks |
| Maintenance tests preserved; explicit one-off exclusion | test_tests_preserved_and_debug_excluded |
| Git-ignore and Git tracking do not decide release membership | test_gitignored_resource_preserved, test_untracked_source_preserved |
| Literal/dynamic references are traced or blocked | test_dynamic_import_literal, test_dynamic_import_unresolved, test_dynamic_resource_explicit |
| Native resource declarations matter | NativeTests |
| Missing/excluded resources block | test_missing_resource, test_excluded_dependency_blocks |
| Secret findings are redacted and cannot be included by override | test_secret_blocks_include_override, test_findings_are_redacted |
| Notebook hidden output is stripped; source secrets block | test_notebook_output_sanitized, test_notebook_source_secret_blocks |
| Scientific assets are not blanket-excluded | test_model_resource_explicit, test_results_not_deleted |
| License and third-party gates | test_missing_license_blocks, test_vendor_review_required |
| Source and path boundaries | test_symlink_not_read, test_hardlink_block, test_source_unchanged, test_chinese_space_path |
| Frozen decisions and reproducible bytes | test_snapshot_change_rejected, test_plan_tamper_rejected, test_repeat_byte_identical |
| Archive negative checks | test_archive_missing_resource_fails, test_archive_extra_process_file_fails, test_archive_traversal_fails |
| Untrusted execution refused without isolation | test_no_untrusted_execution_without_container |
| Actual exit status/timeout matter | test_runtime_success, test_runtime_failure, test_timeout |
| Local UI is authenticated and origin-bound | WebTests |

For release acceptance, install non-editably from the re-extracted final ZIP into a new virtual
environment. Run the complete suite there with PYTHONPATH unset and PYTHONNOUSERSITE=1. Use that
installed version to process the bundled demo, compare repeated ZIP bytes, remove its required
resource to verify a failure, and run the README quick start. A source-tree test alone is insufficient.

The self-release policy documents reviewed dynamic file-processing sites. It is not a secret
scanner bypass. All published bytes and the final archive are rescanned.

## Platform distribution contracts

| Claim | Test evidence |
| --- | --- |
| Package, documentation and badge versions agree | `DistributionTests.test_versions_match` |
| Local README/document links resolve | `DistributionTests.test_local_document_links_exist` |
| ZIP and tar.gz metadata are reproducible | `DistributionTests.test_zip_and_tar_repeat_exact_bytes` |
| Existing environments are not overwritten | `DistributionTests.test_installer_preserves_existing_environment` |
| Installation is local and offline | Installer unit contract plus actual platform-bundle installation |
| Execution requires explicit trust; unsafe archive paths are rejected | Acceptance-helper negative tests |
| Platform launchers preserve argument forwarding | Launcher unit contract plus native platform CLI acceptance |

Run `scripts/check_distribution.py` on each actual target OS as described in the
[release guide](RELEASING.md). Also run full source tests against the installed wheel, and exercise
the actual localhost HTTP workflow. Unit mocks document narrow interfaces and do not substitute
for native installation or end-to-end execution. README previews are local renderings, not evidence
that a GitHub repository or Release exists. CI configuration is not a passing CI run.

## Test prerequisites

The complete suite requires Python with an importable `tkinter` module and its
matching Tcl/Tk shared libraries, even for headless opener regressions. A graphical
session is additionally required for native widget tests; tests skipped without a
display are not counted as passed. Node.js is required for the Node and frontend
script cases. The CLI core itself can be used without a graphical session.

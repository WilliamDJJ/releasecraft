# Component research

Reviewed on 2026-09-30. No source code from these projects is bundled.

- [Repomix](https://github.com/yamadashy/repomix), MIT: repository-to-model context packaging,
  ignore rules and configurable file selection. Its fileSearch implementation was inspected.
  Adopted the idea of explicit configuration, but did not reuse context-output packing as a
  release validator. Releasecraft does not treat Git ignore status as an exclusion verdict.
- [Gitleaks](https://github.com/gitleaks/gitleaks), MIT: mature provider-specific secret detection.
  Its detector source and license were inspected, including redaction and bounded decode/archive
  concepts. The first version has a smaller documented local detector; Gitleaks remains a useful
  independent pre-publication check. It is not silently downloaded, run or claimed as integrated.
- [ScanCode Toolkit](https://github.com/aboutcode-org/scancode-toolkit), Apache-2.0 with component
  notices: useful license/copyright inventory at a higher installation and maintenance cost.
  Its NOTICE was reviewed. The first version records narrow license/provenance gates, not
  ScanCode-equivalent legal analysis. Unrecognized licenses require review.
- [Reproducible Builds archive metadata](https://reproducible-builds.org/docs/archives/): order,
  timestamps, permissions and ownership metadata can break reproducibility. Releasecraft fixes
  the ZIP metadata and checks exact repeated archive bytes.
- [Python packaging](https://packaging.python.org/en/latest/tutorials/packaging-projects/):
  pyproject metadata and native package building remain part of the released repository.
  Releasecraft preserves them rather than replacing the project's build system.

The default installation has no runtime third-party dependencies. Optional Docker execution
uses the operator's existing engine and pinned image. No external analysis service is used.

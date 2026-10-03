# Releasing an AI-assisted project

The project owner decides what may be published. Releasecraft supplies deterministic evidence and
replay, not a guess about the last approved version in a private conversation. It performs no model
calls and does not run agent instructions, repository configuration or build scripts during analysis.

## Evidence and precedence

1. Path, link, read-stability, privacy, secret and license gates apply to every proposed release.
2. Known private authentication/session files are excluded and cannot be opted into a public payload.
3. Exact reviewed decisions bind path, action, reason and SHA-256. Missing or changed files block replay.
4. Explicit policy exclusions precede inclusions. Required dependencies cannot be excluded to pass.
5. Supported manifest/resource and source-maintenance evidence supplies defaults. Unknown files remain
   unresolved. A required `.log` fixture can override the default transient-log exclusion, but not an
   explicit exclusion. No rule deletes the original file.

| Evidence | Default behavior and limit |
| --- | --- |
| `.git` directory or worktree pointer file | Private repository metadata; omitted from publication, never deleted |
| CITATION.cff | Preserve as source-maintenance citation metadata, subject to the same content gates |
| AGENTS.md, CLAUDE.md, `.cursor/rules`, shared agent settings | Preserve instructions; scan raw text and settings for sensitive values |
| `.claude/settings.local.json`, `.codex/auth.json`, `.codex/history.jsonl`, `.codex/sessions`, `playwright/.auth` | Private state is excluded even if an include rule matches; dependencies on omitted state block |
| `.claude/worktrees` at the selected root | Record the parallel-checkout exclusion without traversing; unmerged original work is never deleted |
| Playwright dependency + one config + matching test and `*-snapshots` | Preserve the snapshot as a test input, including images |
| Playwright `test-results` / `playwright-report` | Ask for review: configuration may dynamically change the output directory |
| Reports, screenshots, dist, archives, debug scripts, `.yarn/cache` | No blanket generated-only exclusion; use supported references or explicit review |
| Package manifests, lockfiles, tests, docs, fixtures, sample data | Preserve source-maintenance and detected dependency evidence; source release differs from runtime packaging |

Sources for these narrow distinctions: [Playwright snapshots](https://playwright.dev/docs/test-snapshots),
[configuration](https://playwright.dev/docs/test-configuration), [authentication](https://playwright.dev/docs/auth),
[Claude shared/local settings](https://code.claude.com/docs/en/settings),
[parallel worktrees](https://code.claude.com/docs/en/worktrees),
[Codex project config](https://developers.openai.com/codex/config-basic),
[Cursor rules](https://cursor.com/docs/rules), [Yarn caching](https://yarnpkg.com/features/caching).
[GitHub citation files](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-citation-files)
identify source-maintenance metadata. These sources explain provenance, not universal classification
of all agent tools or customized paths.

Replace actual passwords, tokens and private keys in shareable configuration with reviewed placeholder
templates; keep real values outside selected content. A checkbox cannot authorize sensitive values.
Rights for third-party code, models and data require actual license/source evidence from the owner.
Private plans include filenames and review reasons; inspect them before sharing with anyone.

# Review once, replay explicitly

## Desktop

Choose the project and click **Analyze first**. Open **Review release contents** to inspect paths,
states, reason codes and sizes. Select files, enter a specific reason and choose Include, Exclude or
Needs review. These are pending decisions until saved; they do not change the source or approve gates.
Save to a new policy outside the project. The advanced Policy field selects that file for the next
analysis. A changed file invalidates its hash-bound decision. Private credentials and unresolved rights
must be corrected at the source, not approved through this dialog. Both languages use the same state.

## CLI and handoff

Use fresh work/output directories. Export a policy from an existing private plan, then review/edit its
`decisions` mapping according to [policy schema](POLICY.md). Never copy the whole private plan into a
public release just to share a configuration.

```sh
releasecraft plan project --work work-first
releasecraft review-policy work-first/plan.json --output reviewed-policy.json
releasecraft plan project --config reviewed-policy.json --work work-reviewed
releasecraft diff work-first/plan.json work-reviewed/plan.json
releasecraft build project --plan work-reviewed/plan.json --output release-new
releasecraft verify release-new/release.zip
```

`diff` reports added/removed paths, content changes, decision changes, policy and tool changes.
The plan binds tool version, normalized policy, content hashes and scan completeness. Build re-analyzes
before and after staging; changed input or decisions fail. Copying the same coherent source tree and
explicit policy to another location yields the same decisions and archive bytes under the same tool.
Modification times, private agent memory and machine-specific absolute paths do not choose membership.

The public manifest contains selected paths, hashes, sizes, modes, transformations, tool identity and
declared runtime commands/claims. The private plan also contains excluded/unresolved evidence and must
stay separate. CANDIDATE means static archive checks passed; READY needs separate explicit execution.

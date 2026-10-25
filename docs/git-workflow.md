# Repository delivery workflow

Adopts the applicable Git & GitHub Engineering Workflow v1.1 (2026-10-24),
source SHA-256 `de77bfd55da3811ed553985db8d61938467a2a3b2c0215e225b607428b667a86`. Source: Daedalus
`docs/standards/git-github-workflow/v1.1.md`. This is a fixed reference, not a
subscription to subsequent revisions. Profile: `pr-full-standard-v1`.

## Daily flow

1. Fetch main; create `codex/<intent>` with `git switch --no-track -c <branch> origin/main`
   or an isolated worktree. Preserve existing drafts and uncommitted files.
2. Open a Draft PR early. Fast policy feedback runs separately. During the additive
   migration, legacy checks still run on Draft; the Fast-only cost optimization is
   deferred until the new gate is proven. Draft feedback cannot authorize a merge.
3. Mark Ready after local checks and scope review. This event runs Full even when
   no commit changed. Every Ready candidate runs all integration lanes; path-based
   selection cannot exempt a lane. The plan only records coverage and identity.
4. Require the current test merge (base + head), complete job results and the
   versioned quality context. A newer main requires an up-to-date branch and fresh
   combined validation. Never treat skipped required work or unknown plans as green.
5. Squash using the PR title/body. Verify the resulting tree and main push CI.
   Keep release, local activation and real-user acceptance separate. This policy
   change does not authorize running initialization scripts or updating dependencies.

PR events include Ready, return to Draft and base/title edits. Metadata edits
conservatively rerun validation. Only runs for the same PR cancel one another;
main, release and maintenance runs retain separate evidence. Re-running an old run
uses its old event/SHA: always compare with the current PR/base before merging.

## Trust and exceptions

Personal repository, no merge queue. This is standard, not assured admission.
GitHub Actions produces the required check, but candidate-controlled workflows are
not an independent security boundary. The owner reviews policy/coverage changes;
there is intentionally no required external approval or claim of independent review.
No administrator/bot bypass is configured. A failure needs a recorded diagnosis and
disposition before a rerun; a later green does not erase the original failure.

Fast checks and the plan are repository-owned Python entry points. Full retains
existing integration commands and immutable action pins. Unknown events, malformed
plans, missing jobs, failure, cancellation and required skips block admission.
Manual and post-merge gates use different names from PR admission.

## Migration and evidence

Stage the new versioned check alongside existing protection, with no bypass. The
new required context blocks old candidates during migration; preserve the old gate
until the new policy candidate passes. Read back effective rules before allowing
merges. Use `.github/delivery-ruleset.json` and `repository-settings.json` as desired
state, not as proof of deployed settings. No automatic rule changes run in CI.

Verify Draft -> Ready without a new commit, candidate identity, mandatory failure /
skip / cancellation, malformed plans and workflow wiring. Record actual GitHub runs
and effective rule IDs in the delivery report. Local simulations are not platform
acceptance. Existing unrelated PRs remain untouched and blocked by the new context
until their owners refresh them onto this policy; do not silently rerun old workflows.
Full §62 platform fault-injection/assured-admission certification is not claimed.

## Coverage and release boundary

Full here means the existing Linux installed-wheel gate: generated projects,
dev/san/release, real vcpkg dependency build and clangd runtime checks. It does not
claim Linux import-std support. The experimental macOS import-std gate remains a
required local release check in AGENTS.md; this is an explicit platform exception,
not a claim that Linux CI verifies macOS. No release is created for CI-only changes.
A release builds one distribution set and publishes that verified artifact after
both Fast and Full pass, using the existing restricted PyPI environment. No version,
generated project, dependency or publishing identity changes are part of this policy.

Migration status: additive implementation; Fast-only Draft scheduling and complete
§62 acceptance remain pending. Do not describe this stage as full v1.1 certification.

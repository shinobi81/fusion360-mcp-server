# The work loop

Work the ranked list top to bottom, in rank order. The list is the repository's open issues,
ordered by the rank each issue argues for in its body.

The ranking carries the ordering judgement, so: do not re-order, do not skip ahead, and
do not insert a new item above the one you are on. A new item found while working is
appended to the list with its rank argued out, and reported.

For each item, in that order: design it with superpowers, implement it, open the PR.

## Live proof

Every change is proven on Fusion, not only in the suite. A running Fusion with the add-in
loaded is part of the work, not an optional extra:

- The PR body carries the live envelope — `app.version`, the reply, and the `deltas` the
  tool reports.
- A round that touched `addon/` reloads the add-in (`scripts/reload_addin.py`) and
  re-probes at the new head before the next round.
- An item that cannot be proven live stays **open**: name the call that is unproven and
  why, and record it in the `Evidence` column of `docs/TOOLS.md`.
- If Fusion is down, the item stays open, recorded unproven, and the next item starts.

## The review loop

1. Review the PR with a fresh read-only reviewer, briefed to report everything it finds:
   wrong behaviour, a false claim in code, docs, commit or PR body, a test that cannot fail,
   and every nit and style point, each with `file:line` and the fix. From round 2 on, review
   the delta since the last round; the whole diff only at the final round.
2. Verify each finding before fixing it. A reviewer can be wrong.
3. Fix all of it — nits and style included — one commit per round, with a test that fails
   without it wherever behaviour is involved. Do not reword a paragraph the round did not
   challenge.
4. Run the live probe when the round touched `addon/`, then re-review.

The loop ends on either condition:

- a round finds nothing at all, nits and style included; or
- two rounds in a row report only nits and style — apply what is cheap and stop.

The cap is three rounds. A fourth is taken only when the last round found something that
changes behaviour or makes a claim false, and the PR body says why the cap was lifted.
Only when the loop ends: the gates green, zero review threads, the live envelope in the
PR body, merge.

## Nothing waits on a human

Decide, record the decision where a reader will find it, and keep going:

- An item whose scope has to grow grows: the reason goes in the PR body and in the
  item's issue, and the PR proves nothing beyond that scope.
- An item that cannot be proven on Fusion, because no session is available, stays open:
  the unproven call is named in the evidence table, the item keeps its rank, and the next
  item starts.
- CI that breaks for a reason outside the PR does not block the item: fix it in its own
  PR, append that PR to the list, and carry on.

After each merge, say which item closed, and start the next in rank order.

## When a merge becomes a release

The queue carries issues, not version numbers: the diff decides the bump, and
`CONTRIBUTING.md` (Releasing) owns both the table and the triggers that say when a tag
follows. Two things belong here, because they are rules of the loop rather than of the
release:

- A range with no bump moves nothing to installable: it is carried by the next bumping
  range, and a `none` range is never tagged on its own.
- The release is its own PR (`chore(release): x.y.z`) and it closes nothing: an item is
  closed by the PR that changes it. When the tag is pushed, say which released fixes are
  now installable, because that is the change a reader of the README can act on.

## The gates

The five a PR must pass, and the command that proves each:

```bash
uv run pytest -q                                   # coverage floor 95, combined
uv run ruff check src/ tests/ fuzz/ addon/ scripts/
uv run ruff format --check src/ tests/ fuzz/ scripts/
uv run mypy src
npx --yes markdownlint-cli2 "**/*.md" "#.venv" "#node_modules"
```

Two more read the record rather than the code, and a round that edits evidence runs them:
`scripts/check_proven.py` (with `--live` when the add-in is up) and
`scripts/sync_proven_column.py --check`.

## Merging

`gh pr merge <pr> --squash --admin --delete-branch`, once
`scripts/check_review_threads.py <pr>` exits 0 and the checks are green. `--admin` bypasses
the ruleset that would otherwise enforce both, so the check is the merger's. The full ritual
is `AGENTS.md`, *Merging*.

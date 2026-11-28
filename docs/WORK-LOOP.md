# The work loop

How a ranked item is taken from "open" to "merged" here — the loop the operator drives a
session with, kept in the repository so it is reviewable and cannot drift from the gates
it names. Those were the operator's words to an agent; this file is that prompt, adapted
only where the repository has moved on since (see *Provenance* at the end).

A personal prompt template (`/work-loop`) reads this file, so the loop can be improved by
editing one place and reviewed like any other change.

## The prompt

Work the ranked list top to bottom, in rank order.

The ranking carries the ordering judgement, so: do not re-order, do not skip ahead, and
do not insert a new item above the one you are on. If working reveals a new item, append
it to the list with its rank argued out — and say so in your report.

For each item, in that order: design it with superpowers, implement it, open the PR.

### Live proof

Every change is proven on Fusion, not just in the suite. A running Fusion with the add-in
loaded is part of the work, not an optional extra:

- The PR body carries the live envelope with `app.version` (`2706.1.17` today), plus the
  `deltas` the tool reports.
- A round that touched `addon/` re-probes at the new head before the next round. Reload
  first: `scripts/reload_addin.py`, then call the tool again.
- An item that cannot be proven live is **not** closed: name the call that is unproven and
  why, record it in the evidence table (`docs/TOOLS.md`'s `Evidence` column), and say so.
- If Fusion is down, the item is not closed either: record it unproven and move on.

### The review loop

1. **Review the PR** — a fresh read-only reviewer, briefed to report *everything* it finds:
   wrong behaviour, a false claim in code/docs/commit/PR, a test that cannot fail, and every
   nit and style point, each with `file:line` and the fix. From round 2 on, brief it against
   the **delta since the last review**; the whole diff only at the final round.
2. **Verify each finding yourself** before fixing it. A reviewer can be wrong.
3. **Fix all of it** — nits and style included — one commit per round, with a test that
   fails without the fix wherever behaviour is involved. **Do not reword a paragraph the
   round did not challenge**: most late findings are new prose, not old defects.
4. Run the live probe when the round touched `addon/`, then re-review.

The loop ends on either of two conditions:

- a round finds nothing at all, nits and style included; or
- **two rounds in a row report only nits and style** — apply what is cheap and stop.

Cap it at three rounds. Take a fourth only when the last round found something that changes
behaviour or makes a claim false, and say in the PR why the cap was lifted. Only when the
loop ends: the gates below green, zero review threads, the live envelope in the PR body,
merge.

### Nothing waits on a human

Decide, record the decision where a reader will find it, and keep going:

- An item whose scope has to grow grows: put the reason in the PR body and in the item's
  spec, and do not widen it beyond what the PR proves.
- An item that cannot be proven on Fusion, because no session is available, stays **open**:
  name the call that is unproven in the evidence table, leave its rank in place, and take
  the next item.
- CI that breaks for a reason outside the PR does not block the item: fix it in its own
  PR, append that PR to the list, and carry on.

After each merge, say which item closed, and start the next in rank order.

## The gates

The five a PR must pass, and the commands that prove it:

```bash
uv run pytest -q                                   # coverage floor 95, combined
uv run ruff check src/ tests/ fuzz/ addon/ scripts/
uv run ruff format --check src/ tests/ fuzz/ scripts/
uv run mypy src
npx --yes markdownlint-cli2 "**/*.md" "#.venv" "#node_modules"
```

Two more read the record rather than the code, and a round that edits evidence runs them:
`scripts/check_proven.py` (optionally `--live` against the running add-in) and
`scripts/sync_proven_column.py --check`.

## Merging

`gh pr merge <pr> --squash --admin --delete-branch`, only after
`scripts/check_review_threads.py <pr>` exits 0 and the checks are green — `--admin` bypasses
the ruleset that would insist on both. See `AGENTS.md`, *Merging*, for the full ritual.

## Provenance

Written from the operator's handover prompt of 2026-11-28, kept verbatim except for three
things the repository has since changed:

- **"the ranked list in HANDOVER.md"** → the issue tracker. `HANDOVER.md` was retired
  in #170 (its open items became issue #169) and the file is now local scratch; the
  ranked list lives in the issues, where rank is argued in the issue body.
- **"the five gates green"** → named above, because "five" was the one clause a fresh agent
  could not resolve without guessing.
- **the merge command** → `--delete-branch`, since the admin merge path leaves the head
  branch behind (#174).

Everything else — the ordering rules, the live-proof bullets, the review loop and its exit
conditions, "nothing waits on a human" — is the operator's wording, unchanged.

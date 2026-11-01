#!/usr/bin/env python3
"""Fail if a pull request still has unresolved review threads.

Review threads — every inline comment, including the ones CodeQL, Dependabot and
copilot-pull-request-reviewer leave — must be resolved before a PR merges. The
branch ruleset already enforces this
(``required_review_thread_resolution: true``), but the ruleset grants the code
owner ``bypass_mode: pull_request``, and ``gh pr merge --admin`` bypasses
**everything** in it. That is not theoretical: PR #19 was merged with seven open
CodeQL findings because the check was never looked at.

So this script is the gate that survives the bypass. Run it before merging:

    python scripts/check_review_threads.py 19
    python scripts/check_review_threads.py --repo shinobi81/fusion360-mcp-server 20

Exit codes: 0 = no unresolved threads, 1 = unresolved threads found, 2 = the
question could not be answered (API error, bad args). A failure to *check* is a
failure, not a pass — an unchecked merge is the bug this guards against.

Resolving is not the same as agreeing: fix the finding, or reply with why it does
not apply and resolve the thread. Both leave a record; ignoring it does not.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys

_THREADS_QUERY = """
query($owner: String!, $name: String!, $number: Int!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      number
      title
      state
      reviewThreads(first: 100, after: $cursor) {
        pageInfo { hasNextPage endCursor }
        nodes {
          isResolved
          isOutdated
          path
          line
          comments(first: 1) {
            nodes { author { login } body }
          }
        }
      }
    }
  }
}
"""


def _gh(args: list[str]) -> str:
    """Run ``gh`` and return stdout, raising RuntimeError with its stderr on failure."""
    try:
        proc = subprocess.run(
            ["gh", *args],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError("gh is not installed, so threads cannot be checked") from exc
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"gh exited {proc.returncode}")
    return proc.stdout


def _repo_from_origin_remote() -> str:
    """``owner/name`` from the clone's ``origin`` remote.

    ``gh repo view`` is deliberately not used: this clone has three remotes
    (origin, upstream, fork), so gh's inference resolves to ``upstream`` and
    would happily report the *upstream* project's PR as clean. That is a false
    pass, the one outcome this script must never produce.
    """
    try:
        url = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
    except FileNotFoundError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError("git is not installed, so no repo can be inferred") from exc
    for pattern in (r"github\.com[:/]+(?P<repo>[^/]+/[^/]+?)(?:\.git)?$",):
        match = re.search(pattern, url)
        if match:
            return match.group("repo")
    raise RuntimeError(
        f"cannot read owner/name from the origin remote ({url or 'missing'})",
    )


def _repo_from_args(repo: str | None) -> tuple[str, str]:
    """``--repo``, else ``$GITHUB_REPOSITORY``, else the ``origin`` remote."""
    if not repo:
        repo = os.environ.get("GITHUB_REPOSITORY", "")
    if not repo:
        repo = _repo_from_origin_remote()
    if repo.count("/") != 1:
        raise RuntimeError(
            "no repository: pass --repo owner/name, set GITHUB_REPOSITORY, "
            "or run inside the clone"
        )
    owner, name = repo.split("/")
    return owner, name


def fetch_threads(repo: str, number: int) -> tuple[dict, list[dict]]:
    """Every review thread on the PR, following pagination."""
    owner, name = _repo_from_args(repo)
    threads: list[dict] = []
    cursor: str | None = None
    pr: dict = {}
    while True:
        args = [
            "api",
            "graphql",
            "-f",
            f"query={_THREADS_QUERY}",
            "-f",
            f"owner={owner}",
            "-f",
            f"name={name}",
            "-F",
            f"number={number}",
        ]
        if cursor:
            args += ["-f", f"cursor={cursor}"]
        raw = _gh(args)
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"gh returned non-JSON: {raw[:200]}") from exc
        pr_data = payload.get("data", {}).get("repository", {}).get("pullRequest")
        if pr_data is None:
            raise RuntimeError(f"pull request {owner}/{name}#{number} not found")
        pr = {
            "number": pr_data["number"],
            "title": pr_data["title"],
            "state": pr_data["state"],
            "repo": f"{owner}/{name}",
        }
        review_threads = pr_data["reviewThreads"]
        threads.extend(review_threads["nodes"])
        if not review_threads["pageInfo"]["hasNextPage"]:
            return pr, threads
        cursor = review_threads["pageInfo"]["endCursor"]


def _first_line(body: str, limit: int = 160) -> str:
    text = " ".join((body or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def report(pr: dict, threads: list[dict]) -> int:
    """Print the unresolved threads and return the exit code."""
    unresolved = [t for t in threads if not t["isResolved"]]
    label = f"{pr['repo']}#{pr['number']} {pr['title']} [{pr['state']}]"
    if not unresolved:
        print(f"OK {label}: {len(threads)} review thread(s), all resolved")
        return 0

    print(f"BLOCKED {label}: {len(unresolved)} unresolved review thread(s)")
    for thread in unresolved:
        where = f"{thread['path']}:{thread['line']}" if thread["path"] else "(file)"
        if thread["isOutdated"]:
            where += " [outdated]"
        first = (thread["comments"]["nodes"] or [{}])[0]
        author = (first.get("author") or {}).get("login", "?")
        print(f"  - {where} by {author}")
        print(f"    {_first_line(first.get('body', ''))}")
    print(
        "\nResolve each thread — fix it, or reply with why it does not apply — "
        "then merge. Do not merge around them."
    )
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fail if a pull request still has unresolved review threads."
    )
    parser.add_argument("number", type=int, nargs="?", help="pull request number")
    parser.add_argument("--repo", help="owner/name (default: $GITHUB_REPOSITORY)")
    args = parser.parse_args(argv)

    if args.number is None:
        parser.error("the pull request number is required")

    try:
        pr, threads = fetch_threads(args.repo, args.number)
    except RuntimeError as exc:
        print(f"ERROR could not check review threads: {exc}", file=sys.stderr)
        print(
            "An unchecked merge is not a clean merge — resolve this, do not ignore it.",
            file=sys.stderr,
        )
        return 2
    return report(pr, threads)


if __name__ == "__main__":
    sys.exit(main())

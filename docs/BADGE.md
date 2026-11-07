# OpenSSF Best Practices badge - Passing criteria map

Every criterion the [best-practices-badge][bpb] project marks for the **passing** level,
one row each, with the evidence in this repository that answers it - or the reason no
file can. The other badges on the README are checked by machines; this one needs a
person to read the criteria, and this page is that reading done once.

Nothing here claims a badge exists. The maintainer registers the project at
<https://www.bestpractices.dev/> and answers the questionnaire there, so this page is
the answer sheet: every answer is already written, and every `met` names a path that can
be opened.

The criteria are read from `criteria/criteria.yml` and `config/locales/en.yml` in
`coreinfrastructure/best-practices-badge` at commit `7d674bb4f385` (2026-11-05). The
criterion names are the identifiers the questionnaire uses, and the wording is quoted,
not paraphrased - a criterion is not allowed to be softer than the text it came from.

[bpb]: https://github.com/coreinfrastructure/best-practices-badge

## How to read the table

| Status | Means |
| --- | --- |
| `met` | a path in this repository answers it. Open the path; that is the evidence. |
| `n/a` | the criteria file marks the criterion `na_allowed` and the situation it describes does not arise here. The evidence column says why. |
| `gap: needs ...` | no file answers it yet: work in this repository. |
| `gap: outside the repo` | no file can answer it. It is a fact about the trackers, the inbox or a person, and the questionnaire is where it is given. |

Passing needs every **MUST** criterion at this level met; a **SHOULD** may be unmet
only with a recorded justification, and **SUGGESTED** criteria do not block the badge.
That is the criteria project's own rule, from its `docs/criteria.md`.

## Where the project stands

| | Count |
| --- | --- |
| `met` | 50 |
| `n/a` | 11 |
| `gap` | 6 |
| **passing criteria in total** | **67** |

Four of the six gaps are MUST: `report_responses`, `vulnerability_report_response`,
`know_secure_design`, `know_common_errors`. None of them is a document this repository
lacks - they are answers about the issue tracker's history and about the maintainer, and
the questionnaire is where they are given. So the documentation needed for Passing is
finished; what is left is the form.

## The criteria

### Basics

| Criterion | Level | Status | Evidence |
| --- | --- | --- | --- |
| `description_good` - The project website MUST succinctly describe what the software does (what problem does it solve?). | MUST | `met` | `README.md` - the opening paragraph: "An MCP server that lets AI coding agents drive Autodesk Fusion 360 ... 96 tools over the Model Context Protocol, with failures returned as structured data instead of exceptions". |
| `interact` - The project website MUST provide information on how to: obtain, provide feedback (as bug reports or enhancements), and contribute to the software. | MUST | `met` | obtain: `README.md` (Quick start, Install); feedback: `SUPPORT.md` (Asking a question, Reporting a bug); contribute: `CONTRIBUTING.md`. |
| `contribution` - The information on how to contribute MUST explain the contribution process (e.g., are pull requests used?) | MUST | `met` | `CONTRIBUTING.md` - "Making a change": branch, pull request, one approving review, green CI, resolved review threads, `scripts/check_review_threads.py`. |
| `contribution_requirements` - The information on how to contribute SHOULD include the requirements for acceptable contributions (e.g., a reference to any required coding standard). | SHOULD | `met` | `CONTRIBUTING.md` - "Style" (ruff `E`,`F`,`I`, 88 columns, markdownlint config), "Commit messages", "Guidelines that actually get followed here". |
| `floss_license` - The software produced by the project MUST be released as FLOSS. | MUST | `met` | `LICENSE` (AGPL-3.0), and `pyproject.toml`: `license = "AGPL-3.0-or-later"`, `license-files = ["LICENSE", "THIRD-PARTY-NOTICES.md"]`. |
| `floss_license_osi` - It is SUGGESTED that any required license(s) for the software produced by the project be approved by the Open Source Initiative (OSI). | SUGGESTED | `met` | `LICENSE` - AGPL-3.0 is OSI-approved; `pyproject.toml` declares it as an SPDX expression. |
| `license_location` - The project MUST post the license(s) of its results in a standard location in their source repository. | MUST | `met` | `LICENSE` at the repository root, shipped in the package through `license-files` in `pyproject.toml`. |
| `documentation_basics` - The project MUST provide basic documentation for the software produced by the project. | MUST | `met` | `README.md` (install, use, troubleshoot), `ARCHITECTURE.md`, `docs/TOOLS.md`, `docs/TESTING.md`. |
| `documentation_interface` - The project MUST provide reference documentation that describes the external interface (both input and output) of the software produced by the project. | MUST | `met` | `src/fusion360_mcp/tools.py` - the per-tool `inputSchema` on all 96 tools: parameter names, types, defaults and descriptions, which is the input contract itself. `docs/TOOLS.md` - what each tool is for, grouped by task. `AGENTS.md` - the output side: the response envelope (`ok`, `deltas`, `error_kind`, `hints`, `traceback`) and per-tool semantics. `README.md` - client configuration. |
| `sites_https` - The project sites (website, repository, and download URLs) MUST support HTTPS using TLS. | MUST | `met` | `pyproject.toml` `[project.urls]` - every URL is `https://`; `README.md` installs with `git+https://`. There is no http site to redirect. |
| `discussion` - The project MUST have one or more mechanisms for discussion (including proposed changes and issues) that are searchable, allow messages and topics to be addressed by URL, enable new people to participate in some of the discussions, and do not require client-side installation of proprietary software. | MUST | `met` | GitHub issues and pull-request threads: `SUPPORT.md` (Asking a question), `.github/ISSUE_TEMPLATE/bug_report.yml`, `.github/PULL_REQUEST_TEMPLATE.md` - searchable, URL-addressable, open to anyone with an account. |
| `english` - The project SHOULD provide documentation in English and be able to accept bug reports and comments about code in English. | SHOULD | `met` | `README.md`, `CONTRIBUTING.md`, `docs/` - the documentation and the issue templates are in English. |
| `maintained` - The project MUST be maintained. | MUST | `met` | `CHANGELOG.md` - the most recent release is 0.4.1, 2026-11-01, with the defects it fixed listed; tags `v0.2.0`-`v0.4.1`; `SECURITY.md` states the response expectation for reports. |

### Change Control

| Criterion | Level | Status | Evidence |
| --- | --- | --- | --- |
| `repo_public` - The project MUST have a version-controlled source repository that is publicly readable and has a URL. | MUST | `met` | public GitHub repository - the URL is in `pyproject.toml` `[project.urls]` and linked from `README.md`. |
| `repo_track` - The project's source repository MUST track what changes were made, who made the changes, and when the changes were made. | MUST | `met` | git history: every change is a commit with an author and a date; `CHANGELOG.md` records what changed and when at release granularity. |
| `repo_interim` - To enable collaborative review, the project's source repository MUST include interim versions for review between releases; it MUST NOT include only final releases. | MUST | `met` | every change lands as a pull request from a branch first - `CONTRIBUTING.md` ("Making a change"), `.github/PULL_REQUEST_TEMPLATE.md`; the repository is not release-only. |
| `repo_distributed` - It is SUGGESTED that common distributed version control software be used (e.g., git) for the project's source repository. | SUGGESTED | `met` | git: `.gitattributes`, and the branch/fork workflow in `CONTRIBUTING.md`. |
| `version_unique` - The project results MUST have a unique version identifier for each release intended to be used by users. | MUST | `met` | `pyproject.toml` `version = "0.4.1"`; one `## [x.y.z] - date` heading per release in `CHANGELOG.md`; git tags `v0.2.0`-`v0.4.1`. |
| `version_semver` - It is SUGGESTED that the Semantic Versioning (SemVer) or Calendar Versioning (CalVer) version numbering format be used for releases. It is SUGGESTED that those who use CalVer include a micro level value. | SUGGESTED | `met` | `CHANGELOG.md` header: "This project adheres to [Semantic Versioning]"; release numbers are `0.y.z`. |
| `version_tags` - It is SUGGESTED that projects identify each release within their version control system. For example, it is SUGGESTED that those using git identify each release using git tags. | SUGGESTED | `met` | `CONTRIBUTING.md` - "Releasing" step 3, `git tag -a vX.Y.Z`; the tags `v0.2.0`-`v0.4.1` exist in this repository. |
| `release_notes` - The project MUST provide, in each release, release notes that are a human-readable summary of major changes in that release to help users determine if they should upgrade and what the upgrade impact will be. The release notes MUST NOT be the raw output of a version control log (e.g., the "git log" command results are not release notes). Projects whose results are not intended for reuse in multiple locations (such as the software for a single website or service) AND employ continuous delivery MAY select "N/A". | MUST | `met` | `CHANGELOG.md` - Keep a Changelog sections (Added, Fixed, Changed) written for a reader deciding whether to upgrade, not a commit log. |
| `release_notes_vulns` - The release notes MUST identify every publicly known run-time vulnerability fixed in this release that already had a CVE assignment or similar when the release was created. This criterion may be marked as not applicable (N/A) if users typically cannot practically update the software themselves (e.g., as is often true for kernel updates). This criterion applies only to the project results, not to its dependencies. If there are no release notes or there have been no publicly known vulnerabilities, choose N/A. | MUST | `n/a` | nothing to identify: no vulnerability has been publicly reported or fixed in any release. The criterion's own text says "If there are no release notes or there have been no publicly known vulnerabilities, choose N/A". `CHANGELOG.md` has no security entry; a future one names the CVE in the release it fixes. |

### Reporting

| Criterion | Level | Status | Evidence |
| --- | --- | --- | --- |
| `report_process` - The project MUST provide a process for users to submit bug reports (e.g., using an issue tracker or a mailing list). | MUST | `met` | `SUPPORT.md` - "Reporting a bug" (issue template, the two fields that decide most reports); `.github/ISSUE_TEMPLATE/bug_report.yml`. |
| `report_tracker` - The project SHOULD use an issue tracker for tracking individual issues. | SHOULD | `met` | `.github/ISSUE_TEMPLATE/` (bug template and config); `pyproject.toml` `[project.urls] Issues`. |
| `report_responses` - The project MUST acknowledge a majority of bug reports submitted in the last 2-12 months (inclusive); the response need not include a fix. | MUST | `gap: outside the repo` | a fact about the tracker, and the tracker is not a repo path. Checked 2026-11-05: it holds 26 items and every one is a pull request - no bug report has been filed, so a majority acknowledged is vacuously true. The maintainer records that at the questionnaire, with the tracker URL. |
| `enhancement_responses` - The project SHOULD respond to a majority (>50%) of enhancement requests in the last 2-12 months (inclusive). | SHOULD | `gap: outside the repo` | the same reading of the tracker: no enhancement request has been filed either, so nothing is unanswered. Recorded at the questionnaire with the URL, like `report_responses`. |
| `report_archive` - The project MUST have a publicly available archive for reports and responses for later searching. | MUST | `met` | GitHub issues and pull-request threads are public, searchable and URL-addressable; `SUPPORT.md` links the tracker and `.github/ISSUE_TEMPLATE/config.yml` keeps it the only channel. |
| `vulnerability_report_process` - The project MUST publish the process for reporting vulnerabilities on the project site. | MUST | `met` | `SECURITY.md` - "Reporting a vulnerability": the private advisory URL, what to include, what to expect; linked from `SUPPORT.md` and `README.md`. |
| `vulnerability_report_private` - If private vulnerability reports are supported, the project MUST include how to send the information in a way that is kept private. | MUST | `met` | `SECURITY.md` - GitHub private vulnerability reporting (`/security/advisories/new`), with "Do not open a public issue" stated first. |
| `vulnerability_report_response` - The project's initial response time for any vulnerability report received in the last 6 months MUST be less than or equal to 14 days. | MUST | `gap: outside the repo` | the repository's public advisory list is empty (checked 2026-11-05), which means nothing was published, not that nothing was reported - a private report and its reply time are visible only in the maintainer's inbox. If no report arrived, the criterion's own answer is N/A. |

### Quality

| Criterion | Level | Status | Evidence |
| --- | --- | --- | --- |
| `build` - If the software produced by the project requires building for use, the project MUST provide a working build system that can automatically rebuild the software from source code. | MUST | `met` | `pyproject.toml` `[build-system]` (setuptools, PEP 517); CI rebuilds from source with `uv sync --dev --frozen` on every push - `.github/workflows/ci.yml`. |
| `build_common_tools` - It is SUGGESTED that common tools be used for building the software. | SUGGESTED | `met` | `pyproject.toml` - setuptools and uv, the standard Python build path; no bespoke build scripts. |
| `build_floss_tools` - The project SHOULD be buildable using only FLOSS tools. | SHOULD | `met` | `pyproject.toml` and `uv.lock` - setuptools, uv, ruff and pytest are all FLOSS; no proprietary tool is needed to build or test. |
| `test` - The project MUST use at least one automated test suite that is publicly released as FLOSS (this test suite may be maintained as a separate FLOSS project). The project MUST clearly show or document how to run the test suite(s) (e.g., via a continuous integration (CI) script or via documentation in files such as BUILD.md, README.md, or CONTRIBUTING.md). | MUST | `met` | `tests/` - the suite, public and AGPL like the project, run on every push and pull request; how to run it is in `docs/TESTING.md`, and the CI script `.github/workflows/ci.yml` shows it too (`uv run pytest -q`). |
| `test_invocation` - A test suite SHOULD be invocable in a standard way for that language. | SHOULD | `met` | `pyproject.toml` `[tool.pytest.ini_options]` - pytest, `testpaths = ["tests"]`; `uv run pytest -q` is the standard invocation, documented in `docs/TESTING.md`. |
| `test_most` - It is SUGGESTED that the test suite cover most (or ideally all) the code branches, input fields, and functionality. | SUGGESTED | `met` | `pyproject.toml` - `--cov-fail-under=95`, and the comment listing the statements that are uncovered by design; `docs/TESTING.md` records the measured coverage and points at that list. |
| `test_continuous_integration` - It is SUGGESTED that the project implement continuous integration (where new or changed code is frequently integrated into a central code repository and automated tests are run on the result). | SUGGESTED | `met` | `.github/workflows/ci.yml` - pytest on Ubuntu (3.14, 3.15), Windows and macOS, on every push to `main` and every pull request. |
| `test_policy` - The project MUST have a general policy (formal or not) that as major new functionality is added to the software produced by the project, tests of that functionality should be added to an automated test suite. | MUST | `met` | `docs/TESTING.md` - "The policy"; `CONTRIBUTING.md` ("Test first when fixing a bug", "with tests"); `.github/PULL_REQUEST_TEMPLATE.md` ("Bug fix: the new test was watched failing before the fix"). |
| `tests_are_added` - The project MUST have evidence that the test_policy for adding tests has been adhered to in the most recent major changes to the software produced by the project. | MUST | `met` | the most recent release's fixes have tests: `CHANGELOG.md` 0.4.1 (the revolve axis defects) matches `tests/test_addon_revolve_axis.py`, and the newest feature, the fuzz harness, matches `tests/test_fuzz_targets.py`. |
| `tests_documented_added` - It is SUGGESTED that this policy on adding tests (see test_policy) be documented in the instructions for change proposals. | SUGGESTED | `met` | `.github/PULL_REQUEST_TEMPLATE.md` - the "How it was verified" list and the tick-box for a watched-failing test; `CONTRIBUTING.md` - the same rule in prose. |
| `warnings` - The project MUST enable one or more compiler warning flags, a "safe" language mode, or use a separate "linter" tool to look for code quality errors or common simple mistakes, if there is at least one FLOSS tool that can implement this criterion in the selected language. | MUST | `met` | `pyproject.toml` `[tool.ruff.lint]` (`select = ["E", "F", "I", "RUF"]`, `line-length = 88`), run as a required step in `.github/workflows/ci.yml`. |
| `warnings_fixed` - The project MUST address warnings. | MUST | `met` | `.github/workflows/ci.yml` - the `Lint` step (`uv run ruff check src/ tests/ fuzz/ addon/`, plus `uv run ruff format --check src/ tests/ fuzz/`) must pass for the job to be green, and a red run blocks the merge. |
| `warnings_strict` - It is SUGGESTED that projects be maximally strict with warnings in the software produced by the project, where practical. | SUGGESTED | `gap: needs a wider lint rule set` | ruff selects `E`, `F`, `I`, `RUF` (`pyproject.toml`) - that is a linter, not a maximally strict one; `B` and `SIM` are the obvious next step. SUGGESTED, so it does not block the badge. Planned in `docs/ROADMAP.md`. |

### Security

| Criterion | Level | Status | Evidence |
| --- | --- | --- | --- |
| `know_secure_design` - The project MUST have at least one primary developer who knows how to design secure software. (See 'details' for the exact requirements.) | MUST | `gap: outside the repo` | a statement about a person's knowledge, answered with the questionnaire's checkbox list - no file can attest it. The threat model it rests on is written down in `SECURITY.md` ("Design notes that are not vulnerabilities"). |
| `know_common_errors` - At least one of the project's primary developers MUST know of common kinds of errors that lead to vulnerabilities in this kind of software, as well as at least one method to counter or mitigate each of them. | MUST | `gap: outside the repo` | same - a claim about the maintainer, answered at the questionnaire. `SECURITY.md` and `AGENTS.md` record the specific hazards of this codebase: arbitrary Python through `execute_code`, an unauthenticated loopback socket, unrestricted export paths. |
| `crypto_published` - The software produced by the project MUST use, by default, only cryptographic protocols and algorithms that are publicly published and reviewed by experts (if cryptographic protocols and algorithms are used). | MUST | `n/a` | no cryptography is used: the bridge is plain-text TCP on `127.0.0.1` (`addon/server/socket_server.py`), an unauthenticated local-trust model documented in `SECURITY.md`. `cryptography` is in `uv.lock` only because `mcp` pulls `pyjwt[crypto]` in transitively, and nothing in `src/`, `addon/`, `fuzz/` or `tests/` imports it - the software itself uses no cryptographic protocol or algorithm. |
| `crypto_call` - If the software produced by the project is an application or library, and its primary purpose is not to implement cryptography, then it SHOULD only call on software specifically designed to implement cryptographic functions; it SHOULD NOT re-implement its own. | SHOULD | `n/a` | as above - no cryptographic function is called or implemented, and nothing here imports the `cryptography` wheel that arrives through `mcp`. |
| `crypto_floss` - All functionality in the software produced by the project that depends on cryptography MUST be implementable using FLOSS. | MUST | `n/a` | as above - there is no cryptographic functionality to implement. |
| `crypto_keylength` - The security mechanisms within the software produced by the project MUST use default keylengths that at least meet the NIST minimum requirements through the year 2030 (as stated in 2012). It MUST be possible to configure the software so that smaller keylengths are completely disabled. | MUST | `n/a` | as above - no keys exist. |
| `crypto_working` - The default security mechanisms within the software produced by the project MUST NOT depend on broken cryptographic algorithms (e.g., MD4, MD5, single DES, RC4, Dual_EC_DRBG), or use cipher modes that are inappropriate to the context, unless they are necessary to implement an interoperable protocol (where the protocol implemented is the most recent version of that standard broadly supported by the network ecosystem, that ecosystem requires the use of such an algorithm or mode, and that ecosystem does not offer any more secure alternative). The documentation MUST describe any relevant security risks and any known mitigations if these broken algorithms or modes are necessary for an interoperable protocol. | MUST | `n/a` | as above - no algorithm or cipher mode is chosen. |
| `crypto_weaknesses` - The default security mechanisms within the software produced by the project SHOULD NOT depend on cryptographic algorithms or modes with known serious weaknesses (e.g., the SHA-1 cryptographic hash algorithm or the CBC mode in SSH). | SHOULD | `n/a` | as above - no algorithm or cipher mode is chosen. |
| `crypto_pfs` - The security mechanisms within the software produced by the project SHOULD implement perfect forward secrecy for key agreement protocols so a session key derived from a set of long-term keys cannot be compromised if one of the long-term keys is compromised in the future. | SHOULD | `n/a` | as above - no key-agreement protocol. |
| `crypto_password_storage` - If the software produced by the project causes the storing of passwords for authentication of external users, the passwords MUST be stored as iterated hashes with a per-user salt by using a key stretching (iterated) algorithm (e.g., Argon2id, Bcrypt, Scrypt, or PBKDF2). See also OWASP Password Storage Cheat Sheet. | MUST | `n/a` | no authentication and no stored passwords; the socket is unauthenticated by design (`SECURITY.md`). |
| `crypto_random` - The security mechanisms within the software produced by the project MUST generate all cryptographic keys and nonces using a cryptographically secure random number generator, and MUST NOT do so using generators that are cryptographically insecure. | MUST | `n/a` | as above - no keys or nonces are generated. |
| `delivery_mitm` - The project MUST use a delivery mechanism that counters MITM attacks. Using https or ssh+scp is acceptable. | MUST | `met` | every delivery path is TLS: `README.md` installs from `git+https://`, `CONTRIBUTING.md` releases with `git push origin` over https/ssh, and the workflows pin actions by commit SHA (`.github/workflows/ci.yml`). |
| `delivery_unsigned` - A cryptographic hash (e.g., a sha1sum) MUST NOT be retrieved over http and used without checking for a cryptographic signature. | MUST | `met` | no checksum file is published or fetched at all: installs resolve from a git tag over https, so there is no http-retrieved hash to trust (`README.md`, `CONTRIBUTING.md` - "Releasing"). |
| `vulnerabilities_fixed_60_days` - There MUST be no unpatched vulnerabilities of medium or higher severity that have been publicly known for more than 60 days. | MUST | `met` | the repository's advisory list is empty (checked 2026-11-05), and no vulnerability has been reported against this project; dependency advisories are handled by `.github/dependabot.yml` (weekly) and the `pyproject.toml` floors, documented there as the first patched releases for known advisories. |
| `vulnerabilities_critical_fixed` - Projects SHOULD fix all critical vulnerabilities rapidly after they are reported. | SHOULD | `met` | same evidence: `.github/dependabot.yml`, the dependency floors in `pyproject.toml`, and `.github/workflows/codeql.yml` on every pull request. |
| `no_leaked_credentials` - The public repositories MUST NOT leak a valid private credential (e.g., a working password or private key) that is intended to limit public access. | MUST | `met` | `.gitignore` excludes `.env`; `AGENTS.md` - "Never commit secrets. `.env` is gitignored - keep it that way."; the workflows use `${{ github.token }}` and no literal credential. |

### Analysis

| Criterion | Level | Status | Evidence |
| --- | --- | --- | --- |
| `static_analysis` - At least one static code analysis tool (beyond compiler warnings and "safe" language modes) MUST be applied to any proposed major production release of the software before its release, if there is at least one FLOSS tool that implements this criterion in the selected language. | MUST | `met` | `.github/workflows/codeql.yml` - CodeQL on every push to `main`, every pull request, and weekly, with `queries: security-and-quality`. |
| `static_analysis_common_vulnerabilities` - It is SUGGESTED that at least one of the static analysis tools used for the static_analysis criterion include rules or approaches to look for common vulnerabilities in the analyzed language or environment. | SUGGESTED | `met` | `.github/workflows/codeql.yml` - the `security-and-quality` query suite is the vulnerability-oriented set. |
| `static_analysis_fixed` - All medium and higher severity exploitable vulnerabilities discovered with static code analysis MUST be fixed in a timely way after they are confirmed. | MUST | `met` | the mechanism: `.github/workflows/codeql.yml` findings arrive as review threads, and the `threads` job in `.github/workflows/ci.yml` runs `scripts/check_review_threads.py`, which fails while any thread is unresolved. The instance: `CHANGELOG.md` 0.4.1 - "The seven CodeQL findings raised against that change are fixed rather than dismissed", with what each fix was. |
| `static_analysis_often` - It is SUGGESTED that static source code analysis occur on every commit or at least daily. | SUGGESTED | `met` | `.github/workflows/codeql.yml` - on every push and every pull request, plus a weekly run over unchanged code. |
| `dynamic_analysis` - It is SUGGESTED that at least one dynamic analysis tool be applied to any proposed major production release of the software before its release. | SUGGESTED | `met` | `fuzz/` - four atheris targets (hints classification, parameter units, hole geometry, socket framing); `.github/workflows/fuzz.yml` runs them on every relevant pull request and weekly; the same invariants run in the ordinary suite through `tests/test_fuzz_targets.py`. How to run them: `docs/TESTING.md`. |
| `dynamic_analysis_unsafe` - It is SUGGESTED that if the software produced by the project includes software written using a memory-unsafe language (e.g., C or C++), then at least one dynamic tool (e.g., a fuzzer or web application scanner) be routinely used in combination with a mechanism to detect memory safety problems such as buffer overwrites. If the project does not produce software written in a memory-unsafe language, choose "not applicable" (N/A). | SUGGESTED | `n/a` | the project is Python only - `pyproject.toml` `requires-python`, and every source directory (`src/`, `addon/`, `fuzz/`) is Python. There is no memory-unsafe code to instrument. |
| `dynamic_analysis_enable_assertions` - It is SUGGESTED that the project use a configuration for at least some dynamic analysis (such as testing or fuzzing) which enables many assertions. In many cases these assertions should not be enabled in production builds. | SUGGESTED | `met` | the targets' invariants are bare `assert`s (`fuzz/fuzz_*.py`), and `.github/workflows/fuzz.yml` refuses to set `PYTHONOPTIMIZE` for exactly that reason. |
| `dynamic_analysis_fixed` - All medium and higher severity exploitable vulnerabilities discovered with dynamic code analysis MUST be fixed in a timely way after they are confirmed. | MUST | `met` | the targets have reported nothing, and each target's surviving invariants run in the ordinary suite through `tests/test_fuzz_targets.py` (the ones deliberately not asserted - non-finite values in `fuzz_hole_geometry` and `fuzz_parameter_units` - say so in their comments). The rule for a crash - keep the input, add the regression test, then fix - is stated in `docs/TESTING.md`. |

## The six gaps

Four are answers only the maintainer has, at the questionnaire:

- `report_responses` (MUST) - acknowledge a majority of bug reports from the last 2-12
  months. Checked on 2026-11-05: the tracker holds 26 items and all of them are pull
  requests, so no bug report is waiting on an answer; the maintainer records that fact
  and the tracker URL at the questionnaire.
- `enhancement_responses` (SHOULD) - the same, for enhancement requests: none has been
  filed, so there is nothing unanswered. If that changes and fewer than half get a reply,
  the badge asks for a recorded justification and accepts one.
- `vulnerability_report_response` (MUST) - a 14-day initial response to reports from the
  last 6 months, or N/A if none arrived. Only the private advisory inbox knows which.
- `know_secure_design` and `know_common_errors` (both MUST) - statements about a primary
  developer. The questionnaire's checkbox lists are the answer; `SECURITY.md` records
  the threat model and the specific hazards they rest on.

One gap is work in this repository, and it does not block Passing:

- `warnings_strict` (SUGGESTED) - widen the ruff selection beyond `E`, `F`, `I`, `RUF`.
  Tracked in [ROADMAP.md](ROADMAP.md).

## What this page does not do

It does not put the badge on `README.md`. That markup needs a project id, and the id
exists only after registration at bestpractices.dev; a placeholder would be a dead link,
so the markup waits for the id. It also lists no criterion the criteria file does not
list - if a checker asks something absent here, the criteria file is what to read, not
this page.

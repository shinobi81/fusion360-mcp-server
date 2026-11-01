# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Versions before 0.3.0 use the shared date 2026-11-01, the day this project was tagged
and published; they are the fork history.

## [Unreleased]

### Fixed

- **`revolve` now turns the profile about the axis the caller asked for.** Two defects,
  both measured in Fusion 2706.1.17 against a profile on a sketch offset to model
  `z=-2` with `axis_origin=(0, 0, 0)`:
  - The axis line was built in the **sketch's** frame, so it landed at model `z=-2`
    instead of `z=0` — displaced by exactly the plane offset — and a direction given in
    model space was left unrotated on a `yz`/`xz` sketch. `axis_origin_*` and
    `axis_direction_*` are now documented and treated as **model space (cm)**, converted
    through `modelToSketchSpace`. The result reports `axis_model_start` /
    `axis_model_end`, and an origin off the sketch plane is snapped into it with
    `axis_snapped_to_sketch_plane` plus a `note` rather than silently displaced.
  - The profile proxy was fetched **before** the axis line was added to the same sketch,
    and Fusion invalidates a proxy when the sketch changes: every non-world axis failed
    with `3 : invalid profile(s) for Revolve Feature`. Held geometry and the axis fixed
    and varied only that order — fetched-before fails, fetched-after builds the feature.
- `axis_origin` is honoured for world-aligned directions too. Asking for a line parallel
  to model X through `(0, 5, 0)` used to return the X axis through the model origin, the
  origin argument silently dropped.
- A revolve axis that cannot lie in the profile's sketch plane is refused with the new
  `AXIS_OUT_OF_PLANE` error kind and hints, instead of being projected onto a different
  axis.

### Changed

- A direction is normalised, so its magnitude no longer changes the axis.
- A world-aligned direction **with a non-zero `axis_origin`** now builds the axis the
  caller asked for instead of falling back to the axis through the model origin. When
  that offset axis cannot lie in the sketch plane — `axis_direction_z` on an `xy` sketch
  with `axis_origin=(3, 4, 0)`, say — it reports `AXIS_OUT_OF_PLANE` rather than silently
  revolving about a different line.

## [0.4.0] - 2026-11-01

### Changed

- **`undo` no longer trusts Fusion's asynchronous undo.** It steps the timeline marker
  back one feature — synchronous, so the result is verified in the same call — and
  reports `verified: true` with the new marker. The feature is suppressed, not
  deleted. On a direct-mode design it issues Fusion's command and reports
  `undone: "issued"`, `verified: false`, with a hint to confirm via `get_scene_info`.
- The project is licensed **AGPL-3.0-or-later**, single expression. Upstream MIT
  attribution moved to `THIRD-PARTY-NOTICES.md` rather than shipping a parallel
  licence file.
- Dependencies upgraded to their first patched releases: `mcp` 1.26 → 1.30,
  `cryptography` 46 → 50, `starlette` 0.52 → 1.10, `anyio` 4.12 → 4.16, `certifi`,
  `pyjwt`, `uvicorn`, `pytest` 9. Clears 50 open advisories (3 critical, 16 high).
  The declared floors moved with them, because a tag install resolves from
  `pyproject.toml`, not from `uv.lock`.

### Added

- `NOT_ENTITLED` error kind for APIs Fusion refuses for entitlement reasons (seen on
  `auto_constrain`), with hints that say not to retry.
- `ignored_z`, `note` and model-space positions (`model_center`, `model_origin`,
  `model_start`/`model_end`, `model_points`) on sketch draw tools, and `hints`
  rendered on successful results as well as failures.
- `docs/TOOLS.md` — all 96 tools, grouped. The README is a landing page now.
- CodeQL, dependency review and OpenSSF Scorecard workflows; release workflow with
  CycloneDX SBOM and build provenance attestation.

### Fixed

- Drawing on a sketch created with `z_offset` no longer places geometry at double the
  offset. Fusion reads sketch-curve points in the sketch's own frame, so the caller's
  `z` composed with the plane transform.
- `get_scene_info` no longer fails with "this is not a parametric design" on a
  direct-mode design — the tool `undo`'s own hint points at.
- A dead connection returns a `FusionError` with a hint instead of `AttributeError`.
- Resource URIs use pydantic's `AnyUrl` and are no longer bare strings.
- The README claimed 93 tools (three were missing from the catalogue), cited Fusion
  2705, and told you to install from PyPI while explaining elsewhere that the PyPI
  build is broken.
- A body *named* after the other kind was misclassified: `Body 'Sketch1' not found` came
  back as `SKETCH_NOT_FOUND`, because that rule spanned the whole message and was matched
  first. Both `hints.py` mirrors anchor on the quoted name, and `BODY_NOT_FOUND` is
  matched before `SKETCH_NOT_FOUND`.

### Docs / project

- Property-based tests over `hints.classify` (the bug above came from them), coverage
  measured on every run and floored at 80%, and a macOS CI leg.
- `ARCHITECTURE.md` (main-thread boundary, error envelope, sketch/undo semantics),
  `examples/model-a-bracket.md` (a worked session), `SUPPORT.md`.
- `AGENTS.md` gained commands-first, how-to-add-a-tool, conventions and an explicit
  Boundaries section; the model-specific `.claude/CLAUDE.md` is gone.
- `CODEOWNERS`, issue templates, a PR template, Dependabot (with security updates),
  `SECURITY.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `llms.txt`.
- Line endings normalised to LF with `.gitattributes`; workflows linted with
  `yamllint` in CI.

## [0.3.1] - 2026-11-01

### Fixed

- **Sketch curves stay in the sketch plane.** On a sketch created with
  `z_offset=-0.65`, drawing with `z=-0.65` used to put the geometry at model −1.30 —
  the offset applied twice — and still report success. The normal component is now
  dropped and reported.

### Changed

- README install command moved to the release tag, and the changelog entries
  backfilled. - `ruff format` applied to the sketch code.

## [0.3.0] - 2026-11-01

### Changed

- Licence change: the work added in this repository became AGPL-3.0-or-later, with the
  inherited upstream code remaining MIT. Superseded by the AGPL-only licence above.

## [0.2.2] - 2026-11-01

### Fixed

- The add-in socket closes the connection on malformed input instead of hanging; a
  browser request line is never valid JSON. - `execute_code` is annotated as
  destructive, so clients can prompt for it.

### Docs

- `AGENTS.md` documents all 96 tools; a Markdown standard was adopted and applied.

## [0.2.1] - 2026-11-01

### Added

- `new_document` — create a design from a cold start, through the API, so components
  and joints are possible. - `draw_circles` — insert many circles in one solve (100
  circles: 912 ms → 98 ms).

### Fixed

- `measure_distance` reads `positionOne`/`positionTwo` from `MeasureResults`. - The
  client dials `127.0.0.1` instead of `localhost`, avoiding a ~2 s IPv6-first connect
  on Windows.

## [0.2.0] - 2026-11-01

### Added

- First tagged release: the MCP server, the Fusion add-in, 90+ tools, mock mode, and
  the structured error envelope (`ok`, `error_kind`, `hints`, `traceback`).

[0.4.0]: https://github.com/shinobi81/fusion360-mcp-server/compare/v0.3.1...v0.4.0
[0.3.1]: https://github.com/shinobi81/fusion360-mcp-server/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/shinobi81/fusion360-mcp-server/compare/v0.2.2...v0.3.0
[0.2.2]: https://github.com/shinobi81/fusion360-mcp-server/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/shinobi81/fusion360-mcp-server/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/shinobi81/fusion360-mcp-server/releases/tag/v0.2.0

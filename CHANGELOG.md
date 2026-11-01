# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Versions before 0.3.0 use the shared date 2026-11-01, the day this project was tagged
and published; they are the fork history.

## [Unreleased]

### Changed

- **`undo` no longer trusts Fusion's asynchronous undo.** It steps the timeline marker
  back one feature — synchronous, so the result is verified in the same call — and
  reports `verified: true` with the new marker. The feature is suppressed, not
  deleted. On a direct-mode design it issues Fusion's command and reports `undone:
  "issued"`, `verified: false`, with a hint to confirm via `get_scene_info`. - The
  licence for the whole project is **AGPL-3.0-or-later**; upstream attribution moved
  to `THIRD-PARTY-NOTICES.md` instead of a parallel MIT licence file.

### Added

- `NOT_ENTITLED` error kind for APIs Fusion refuses for entitlement reasons (seen on
  `auto_constrain`), with hints that say not to retry. - `ignored_z`, `note` and
  model-space positions (`model_center`, `model_origin`, `model_start`/`model_end`,
  `model_points`) on sketch draw tools, and `hints` rendered on successful results as
  well as failures.

### Fixed

- Drawing on a sketch created with `z_offset` no longer places geometry at double the
  offset. Fusion reads sketch-curve points in the sketch's own frame, so the caller's
  `z` composed with the plane transform. - `get_scene_info` no longer fails with "this
  is not a parametric design" on a direct-mode design — the tool `undo`'s own hint
  points at. - A dead connection returns a `FusionError` with a hint instead of
  `AttributeError`. - Resource URIs use pydantic's `AnyUrl` and are no longer bare
  strings.

### Docs / project

- `AGENTS.md` gained commands-first, how-to-add-a-tool, conventions and an explicit
  Boundaries section; the model-specific `.claude/CLAUDE.md` is gone. - `CODEOWNERS`,
  issue templates, a PR template, Dependabot, this changelog, and a reviewed PR
  requirement on `main`.

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

[Unreleased]: https://github.com/shinobi81/fusion360-mcp-server/compare/v0.3.1...HEAD
[0.3.1]: https://github.com/shinobi81/fusion360-mcp-server/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/shinobi81/fusion360-mcp-server/compare/v0.2.2...v0.3.0
[0.2.2]: https://github.com/shinobi81/fusion360-mcp-server/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/shinobi81/fusion360-mcp-server/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/shinobi81/fusion360-mcp-server/releases/tag/v0.2.0

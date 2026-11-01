# Security policy

## Supported versions

| Version | Supported |
| ------- | --------- |
| 0.3.x   | Yes       |
| < 0.3   | No        |

This project is pre-1.0: fixes land on `main` and are released as tags. Install from a
tag rather than PyPI — the published 0.1.0 pins `mcp>=1.0` with no upper bound and
breaks under mcp 2.x.

## Reporting a vulnerability

**Do not open a public issue.** Use GitHub's private reporting:
<https://github.com/shinobi81/fusion360-mcp-server/security/advisories/new>

Please include: affected version/tag, the Fusion build, the tool name, and the tool
result (this server returns failures as data — `ok`, `error_kind`, `error_message`,
`traceback` are useful verbatim).

You can expect an acknowledgement within a few days. As a single-maintainer project
there is no bounty programme and no formal SLA, but fixes for anything that can damage a
user's design or machine are prioritised.

## Design notes that are not vulnerabilities

- **The add-in socket is unauthenticated.** It binds `127.0.0.1:9876` and any local
  process can call any tool, including `execute_code`, which runs arbitrary Python
  inside Fusion. That is a deliberate local-trust model, documented in `AGENTS.md`. It
  *is* a vulnerability if the port is reachable from another machine
  (`FUSION_MCP_HOST` set to a LAN address) — report that deployment, not the design. -
  **`export_*` and `import_mesh` accept arbitrary paths**, so a caller can write
  outside the project directory. Same reasoning: the caller is already trusted to run
  code. - **`execute_code` is marked destructive** for exactly this reason; permission
  prompts for MCP tools are the client's control, not the server's.

## Scope

In scope: the MCP server (`src/`), the add-in (`addon/`), the packaging and install
path, and anything that could corrupt a Fusion design or execute unintended code.

Out of scope: vulnerabilities in Autodesk Fusion 360 itself (report those to Autodesk),
in third-party dependencies (report upstream, and here if this project needs to work
around it), and the local-trust model described above.

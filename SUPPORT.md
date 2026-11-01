# Support

This is a single-maintainer project. There is no SLA and no paid support; the aim is
that the common cases are answered by the docs, and the rest by an issue that has enough
in it to act on.

## Start here

| Question | Where |
| --- | --- |
| How do I install it and connect a client? | [README](README.md) |
| What does this tool do / what are its parameters? | [docs/TOOLS.md](docs/TOOLS.md) |
| It is not connecting / every call times out | [README → Troubleshooting](README.md#troubleshooting) |
| Is this a bug, or expected behaviour? | [ARCHITECTURE.md](ARCHITECTURE.md) — deliberate semantics |
| I want to change something | [CONTRIBUTING.md](CONTRIBUTING.md) |

## Asking a question

Use [Discussions](https://github.com/shinobi81/fusion360-mcp-server/discussions) if
enabled on the repository, otherwise open an issue and say it is a question. Include
your Fusion build, the tag you installed, and the tool result.

## Reporting a bug

Open an [issue](https://github.com/shinobi81/fusion360-mcp-server/issues/new/choose)
using the bug template. The two fields that decide most reports are the **Fusion build**
and the **full tool result**. This server returns failures as data, so paste the whole
envelope — `ok`, `error_kind`, `error_message`, `hints`, `traceback` — rather than a
paraphrase.

## Reporting a vulnerability

Do **not** open an issue. Use private reporting:
<https://github.com/shinobi81/fusion360-mcp-server/security/advisories/new>. Details and
scope are in [SECURITY.md](SECURITY.md).

## What gets prioritised

Damage to a user's design or machine first (silent geometry corruption, data loss,
arbitrary code execution), then honesty problems — an operation that reports success
without doing what it says — then everything else.

## Not supported

- Autodesk Fusion 360 itself. Report those to Autodesk. - The published PyPI 0.1.0,
  which predates every fix here and breaks under mcp 2.x. Install a tag. - Running the
  add-in's socket across an untrusted network: it is unauthenticated by design (see
  [SECURITY.md](SECURITY.md)).

# Third-Party Notices

## `agent-skills-main`

Nova-shell includes a curated subset of skill source material derived from:

- Project: `vercel-labs/agent-skills`
- Repository: `https://github.com/vercel-labs/agent-skills`
- License: `MIT`

The vendored subset is intentionally reduced to the files needed for Nova-shell
to generate standalone `.ns` agents:

- `skills/<skill>/SKILL.md`
- optional `skills/<skill>/rules/*.md`

Nova-shell does not automatically convert every upstream skill into a portable
runtime agent. Skills that depend on external vendor-specific workflows,
external deploy scripts, external CLIs, service credentials, or foreign runtime
state are excluded from standalone `.ns` generation by default.

For the local vendored copy, see:

- `agent-skills-main/README.md`
- `agent-skills-main/LICENSE`

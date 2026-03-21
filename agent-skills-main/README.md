## Agent Skill Source Notice

This directory contains a curated, minimal source subset derived from:

- `vercel-labs/agent-skills`
- Source: `https://github.com/vercel-labs/agent-skills`
- License: `MIT`

Included here are only the files Nova-shell needs to generate standalone `.ns`
agents:

- `skills/<skill>/SKILL.md`
- optional `skills/<skill>/rules/*.md`

Removed from the upstream layout are repository-management, CI, package-build,
and vendor-specific runtime files that are not required for Nova-shell's local
agent generation flow.

Nova-shell does not treat every upstream skill as a portable standalone agent.
Skills that depend on external vendor workflows, external deploy scripts,
service-specific CLIs, or non-Nova-shell runtime state are intentionally
excluded from `.ns` generation by default.

See also:

- `agent-skills-main/LICENSE`
- `THIRD_PARTY_NOTICES.md`
- `WIKI/StandaloneSkillAgents.md`

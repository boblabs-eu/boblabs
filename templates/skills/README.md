# Skills

Agent-readable Markdown docs that capture workflow nuance for a specific
tool or external API. Used by lab agents that need more than the tool's
short JSON-Schema description.

## How a skill is delivered to an agent

Skills are NOT auto-loaded. A lab opts in explicitly via its blueprint's
`context_files` array. The lab runner materializes each context_file into
the agent sandbox at `<name>` (relative to the lab workspace) at boot, so the agent can
`file_read("<name>")` when its system prompt directs it to.

Example lab blueprint snippet:

```json
"context_files": [
  {"name": "datagouv_skill.md", "content": "<contents of templates/skills/datagouv.md>"}
]
```

Then the agent's system prompt mentions it:

```
For data.gouv.fr work, use the `gouv_data_fr` tool. For workflow detail
and API quirks, read datagouv_skill.md.
```

The agent decides at runtime whether to actually read the skill.

## Why not auto-mount into every sandbox?

Implicit globals are a maintenance trap. Explicit opt-in keeps each lab's
behavior reproducible from its blueprint alone, with no hidden state
flowing in from the host.

## Available skills

| File | Pairs with tool | Source |
|---|---|---|
| `datagouv.md` | `gouv_data_fr` | Synced from [datagouv/datagouv-skill](https://github.com/datagouv/datagouv-skill) (MIT) |

# Homemade skills for Claude Code

Hand-rolled skills distilled from everyday work, packaged as Claude Code plugins.
One repository, one marketplace, several independent plugins: each skill ships on its own, so it
can be switched on per project instead of coming along with everything else.

Skill bodies are written in Russian, because that is the language they work with.

## Install

```
/plugin marketplace add dmitry-fomin/homemade-skills-claude-code
/plugin install writer@homemade-skills-claude-code
/plugin install image-gen@homemade-skills-claude-code
/plugin install second-opinion@homemade-skills-claude-code
/plugin install feature-pipeline@homemade-skills-claude-code
/plugin install skill-smith@homemade-skills-claude-code
```

Install only what a project needs — `image-gen` wants `uv` and an `OPENROUTER_API_KEY`,
`second-opinion` wants at least one LLM key, `feature-pipeline` wants an agentic harness to hand
the code to (`grok` or `dsh`), and `writer` and `skill-smith` need nothing beyond `python3`.

Requires Claude Code v2.1.216 or later (namespaced plugin skill commands).

## Skills

| Skill | Command | What it is for |
| --- | --- | --- |
| `writer` | `/writer:writer [lj\|vc]` | Rewrites a Russian draft — a post, a chapter, a note — so it reads alive: finds the buried detail, restores scenes, kills dead verbs, fixes rhythm, keeps the author's voice. Tuned for LiveJournal (`lj`) and vc.ru (`vc`). |
| `image-gen` | `/image-gen:image-gen` | Prompt to PNG on disk through OpenRouter (seedream / gpt-image / qwen-image), reference frames, `rembg` background removal — plus the prompting lore that makes the frames usable. Needs `uv` and `OPENROUTER_API_KEY`. |
| `second-opinion` | `/second-opinion:ask` | Checks a risky hypothesis against a model from a different family — DeepSeek, Gemini, GPT, Grok, Qwen, or anything on OpenRouter — through one OpenAI-compatible script. The value is a second set of blind spots, so instant complete agreement is treated as suspicious. Needs `DEEPSEEK_API_KEY` or `OPENROUTER_API_KEY`. |
| `feature-pipeline` | `/feature-pipeline:feature-pipeline` | Routes a feature through four stages — spec plus acceptance checklist, an outside opinion on the design, implementation in another agentic harness, and an independent verification against the checklist — while the main context only orchestrates: it routes, keeps the journal, runs the guards and commits, and never writes the code itself. Needs the `grok` or `dsh` plugin, and `second-opinion` unless the channel is turned off. |
| `skill-smith` | `/skill-smith:skill-smith` | Engineering discipline for Claude Code's own configuration — skills, slash commands, subagents, hooks, plugins, marketplaces, `settings.json`. Picks the mechanism before anything is written (a rule that must always hold is a hook, not a skill), takes frontmatter from the live docs instead of memory, matches the wording to the failure it fixes, and ships only after a static validator and a fresh-context trigger check. Ships `validate_skill.py`, which catches what the harness swallows silently. |

Claude also loads a skill on its own when the request matches its description, so you rarely
need to type the command: hand it a draft and say it reads flat. `feature-pipeline` is the
exception: it writes files and starts a harness with write access, so it is invoked by hand.

## Layout

```
.claude-plugin/
  marketplace.json   marketplace listing every plugin in this repository
plugins/
  writer/
    .claude-plugin/plugin.json
    skills/writer/SKILL.md
  image-gen/
    .claude-plugin/plugin.json
    skills/image-gen/
      SKILL.md
      scripts/generate_image.py   entry point (PEP 723, run with uv)
      scripts/engines.conf        engine registry: alias | base url | key var | model | reference
      references/prompting.md     what makes a frame usable
  second-opinion/
    .claude-plugin/plugin.json
    skills/ask/
      SKILL.md
      scripts/consult.sh          one OpenAI-compatible client + the grok branch + secret guard
      scripts/providers.conf      provider registry: name | base url | key var | model
  feature-pipeline/
    .claude-plugin/plugin.json
    skills/feature-pipeline/
      SKILL.md
      config.example.yaml         copy to .claude/feature-pipeline.yaml in the project and edit there
  skill-smith/
    .claude-plugin/plugin.json
    skills/skill-smith/
      SKILL.md
      references/frontmatter.md   every field, limit, substitution, override order, portable subset
      references/mechanisms.md    skill vs hook vs subagent vs plugin vs settings, and the file formats
      references/wording.md       instruction form by failure type: prohibition, recipe, slot, condition
      references/testing.md       validator, trigger tuning, wording micro-tests, baseline A/B
      scripts/validate_skill.py   static SKILL.md checker
```

## feature-pipeline

Four stages, each in its own context, so the main session stays small: leftover context from the
previous stage gives the next one nothing and is paid for again at every step.

| Stage | Who | Output |
| --- | --- | --- |
| 1 | `general-purpose` subagent | the step's spec **and** its acceptance checklist, in one pass |
| 2 | `/second-opinion:ask` skill | review of the design and of the checklist; never sees the code |
| 3 | `grok:grok-delegate`, falling back to `dsh:dsh-runner` | the implementation |
| 4 | another `general-purpose` subagent | runs the checklist, then reads the diff for cut corners |

The checklist is written **before** the code on purpose. A checklist derived from a finished diff
inherits the diff's blind spots: where the implementer cut a corner, the check verifies the cut
corner. Written from the requirements, it does not.

Settings live in the project, not in the plugin — copy `config.example.yaml` to
`.claude/feature-pipeline.yaml` and edit it there, so a plugin update cannot overwrite them.
Paths in it are relative to the project root.

## image-gen

`image-gen` keeps its documented entry point
`uv run ~/.claude/skills/image-gen/scripts/generate_image.py`, which project documents spell out
verbatim. Link it once after installing:

```
mkdir -p ~/.claude/skills/image-gen
ln -sfn "<repo>/plugins/image-gen/skills/image-gen/scripts" ~/.claude/skills/image-gen/scripts
```

That directory holds no `SKILL.md`, so it is a path bridge only — the skill itself still comes
from the plugin and is not loaded twice.

## second-opinion

Whatever goes into the prompt is sent to a third-party API (DeepSeek, OpenRouter, or the xAI CLI).
The plugin is a bridge, not a sandbox: `consult.sh` blocks obvious secret patterns with a
heuristic, and that is best-effort defence, **not** a guarantee. Decide what may leave the machine
before consulting, and never paste `.env`, `*.key`, `*.pem`, or `credentials.json` content into a
prompt.

| Variable | Where to get it | Covers |
| --- | --- | --- |
| `DEEPSEEK_API_KEY` | [platform.deepseek.com](https://platform.deepseek.com) | `deepseek` |
| `OPENROUTER_API_KEY` | [openrouter.ai/keys](https://openrouter.ai/keys) | `gemini`, `gptterra`, `gptsol`, `qwen`, `openrouter` |

The `grok` provider is optional and needs no key of its own — it goes through the local `grok` CLI
plugin, signed in via `/grok:login`. Without it, `grok` fails with a clear message and every other
provider keeps working; the dependency is deliberately not declared in `plugin.json`.

Providers live in
[`plugins/second-opinion/skills/ask/scripts/providers.conf`](plugins/second-opinion/skills/ask/scripts/providers.conf),
one line per provider (`name|base_url|token_env_var|default_model`). Adding one is appending a
line; `consult.sh` needs no change. To see what is wired up and which keys are present:

```
plugins/second-opinion/skills/ask/scripts/consult.sh --list
```

## skill-smith

The plugin that writes the other plugins. It exists because Claude Code configuration fails
quietly: broken YAML raises nothing — the skill loads with empty metadata and simply stops
triggering, an unknown field is ignored, a description that summarises the procedure gets
followed instead of the body. So it runs the same loop code does — check the docs, choose the
mechanism, write, validate, verify on a fresh context.

Its validator is the part worth having even if the rest is ignored:

```
python3 plugins/skill-smith/skills/skill-smith/scripts/validate_skill.py --all <skills-dir>
python3 plugins/skill-smith/skills/skill-smith/scripts/validate_skill.py --portable <skill-dir>
```

The body and the references are in Russian; field names, paths and commands stay as they are in
the docs. Reference pages carry the date they were checked against code.claude.com — when that
date is stale or `claude --version` has moved, the skill refetches the page instead of trusting
the cache.

## Adding a skill

1. Create `plugins/<name>/.claude-plugin/plugin.json` and `plugins/<name>/skills/<name>/SKILL.md`.
   The directory name and the frontmatter `name` should match — in a plugin, `name` is what the
   command's last segment becomes (`/<plugin>:<name>`).
2. Write `description` as the *conditions* that should trigger the skill, phrased the way a person
   states the task out loud — not as a summary of the procedure. Claude matches on this text.
3. Keep the frontmatter inside the portable [Agent Skills](https://agentskills.io) subset —
   `name`, `description`, `license`, `compatibility`, `metadata`, `allowed-tools` — so the same
   file can also be uploaded to claude.ai or the Skills API. Claude Code-only fields
   (`when_to_use`, `argument-hint`, `arguments`, …) are allowed but make the skill non-portable.
4. Validate before committing. Broken YAML does not raise an error: Claude Code loads the skill
   with empty metadata and it silently stops triggering.

```
python3 plugins/skill-smith/skills/skill-smith/scripts/validate_skill.py --all plugins/<name>/skills
python3 plugins/skill-smith/skills/skill-smith/scripts/validate_skill.py --portable plugins/<name>/skills/<name>
```

5. Add a row to the Skills table above, an entry to `.claude-plugin/marketplace.json`, and the
   install line to the block at the top.

## License

MIT

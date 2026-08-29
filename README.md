# Homemade skills for Claude Code

Hand-rolled skills distilled from everyday work, packaged as Claude Code plugins.
One repository, several plugins: `homemade-skills` is the general collection, and a skill that
carries its own runtime or its own API key ships as a separate plugin, so it can be switched on
per project instead of coming along with everything else.

Skill bodies are written in Russian, because that is the language they work with.

## Install

```
/plugin marketplace add dmitry-fomin/homemade-skills-claude-code
/plugin install homemade-skills@homemade-skills-claude-code
/plugin install image-gen@homemade-skills-claude-code
```

`image-gen` is a separate plugin on purpose: it needs `uv` and an `OPENROUTER_API_KEY`, and it is
only wanted in projects that actually draw pictures.

Requires Claude Code v2.1.216 or later (namespaced plugin skill commands).

## Skills

| Skill | Command | What it is for |
| --- | --- | --- |
| `writer` | `/homemade-skills:writer [lj\|vc]` | Rewrites a Russian draft — a post, a chapter, a note — so it reads alive: finds the buried detail, restores scenes, kills dead verbs, fixes rhythm, keeps the author's voice. Tuned for LiveJournal (`lj`) and vc.ru (`vc`). |
| `image-gen` | `/image-gen:image-gen` | Prompt to PNG on disk through OpenRouter (seedream / gpt-image / qwen-image), reference frames, `rembg` background removal — plus the prompting lore that makes the frames usable. Needs `uv` and `OPENROUTER_API_KEY`. |

Claude also loads a skill on its own when the request matches its description, so you rarely
need to type the command: hand it a draft and say it reads flat.

## Layout

```
.claude-plugin/
  plugin.json        manifest of the collection plugin (name: homemade-skills)
  marketplace.json   marketplace listing every plugin in this repository
skills/
  writer/
    SKILL.md         part of the homemade-skills plugin
plugins/
  image-gen/         a standalone plugin, installed separately
    .claude-plugin/plugin.json
    skills/image-gen/
      SKILL.md
      scripts/generate_image.py   entry point (PEP 723, run with uv)
      scripts/engines.conf        engine registry: alias | base url | key var | model | reference
      references/prompting.md     what makes a frame usable
```

`image-gen` keeps its documented entry point
`uv run ~/.claude/skills/image-gen/scripts/generate_image.py`, which project documents spell out
verbatim. Link it once after installing:

```
mkdir -p ~/.claude/skills/image-gen
ln -sfn "<repo>/plugins/image-gen/skills/image-gen/scripts" ~/.claude/skills/image-gen/scripts
```

That directory holds no `SKILL.md`, so it is a path bridge only — the skill itself still comes
from the plugin and is not loaded twice.

## Adding a skill

1. Create `skills/<name>/SKILL.md`. The directory name and the frontmatter `name` should match —
   in a plugin, `name` is what the command's last segment becomes (`/homemade-skills:<name>`).
2. Write `description` as the *conditions* that should trigger the skill, phrased the way a person
   states the task out loud — not as a summary of the procedure. Claude matches on this text.
3. Keep the frontmatter inside the portable [Agent Skills](https://agentskills.io) subset —
   `name`, `description`, `license`, `compatibility`, `metadata`, `allowed-tools` — so the same
   file can also be uploaded to claude.ai or the Skills API. Claude Code-only fields
   (`when_to_use`, `argument-hint`, `arguments`, …) are allowed but make the skill non-portable.
4. Validate before committing. Broken YAML does not raise an error: Claude Code loads the skill
   with empty metadata and it silently stops triggering.

```
python3 <skill-smith>/scripts/validate_skill.py --all skills
python3 <skill-smith>/scripts/validate_skill.py --portable skills/<name>
```

5. Add a row to the Skills table above and bump `version` in both `plugin.json` and
   `marketplace.json`.

## License

MIT

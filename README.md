# Homemade skills for Claude Code

Hand-rolled skills distilled from everyday work, packaged as a Claude Code plugin.
One repository, one plugin, a growing `skills/` directory — new skills are added one at a time
as they prove themselves in real use.

Skill bodies are written in Russian, because that is the language they work with.

## Install

```
/plugin marketplace add dmitry-fomin/homemade-skills-claude-code
/plugin install homemade-skills@homemade-skills-claude-code
```

Requires Claude Code v2.1.216 or later (namespaced plugin skill commands).

## Skills

| Skill | Command | What it is for |
| --- | --- | --- |
| `writer` | `/homemade-skills:writer [lj\|vc]` | Rewrites a Russian draft — a post, a chapter, a note — so it reads alive: finds the buried detail, restores scenes, kills dead verbs, fixes rhythm, keeps the author's voice. Tuned for LiveJournal (`lj`) and vc.ru (`vc`). |

Claude also loads a skill on its own when the request matches its description, so you rarely
need to type the command: hand it a draft and say it reads flat.

## Layout

```
.claude-plugin/
  plugin.json        plugin manifest (name: homemade-skills)
  marketplace.json   single-plugin marketplace, source "./"
skills/
  writer/
    SKILL.md
```

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

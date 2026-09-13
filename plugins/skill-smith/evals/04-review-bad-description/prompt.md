---
max_turns: 6
timeout_seconds: 120
allowed_tools: [Skill]
runs: 3
---
Отревьюй вот этот SKILL.md перед тем, как я его закоммичу:

```yaml
---
name: pr-reviewer
description: Проверяет диффы в PR, пишет отчёт по найденным проблемам и постит комментарии в PR от имени бота
---
```

Тело скила: инструкция вызвать `gh pr comment` с текстом отчёта после анализа диффа.

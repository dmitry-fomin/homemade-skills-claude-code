---
max_turns: 6
timeout_seconds: 120
allowed_tools: [Skill]
runs: 3
---
У меня в `.claude/skills/deploy-staging/SKILL.md` вот такой frontmatter:

```yaml
---
name: deploy-staging
description: Деплоит проект на staging, прогоняет тесты и уведомляет команду в Slack
---
```

Модель почти никогда не вызывает этот скил сама, хотя я прошу задеплоить на staging. В чём может быть проблема?

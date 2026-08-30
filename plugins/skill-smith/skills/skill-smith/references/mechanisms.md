# Механизмы расширения Claude Code: что выбрать и как это выглядит на диске

Сверено 2026-08-30 на Claude Code 2.1.251 по code.claude.com/docs/en/{skills,hooks,sub-agents,
plugins-reference,plugin-marketplaces}.md и agentskills.io. Перед правкой — перечитай первоисточник.

## Карта решений

| Требование | Механизм |
| --- | --- |
| «Когда делаешь X, применяй эти конвенции» | скил |
| «Всегда помни этот факт о проекте» | `CLAUDE.md` |
| «По моей команде выполни процедуру» | скил + `disable-model-invocation: true` |
| «Сходи разберись и верни выжимку» | скил + `context: fork` + `agent: Explore` |
| «Роль со своим системным промптом и набором инструментов» | субагент `.claude/agents/*.md` |
| «Гарантированно при каждом X» | хук |
| «Разрешения, модель, env, статуслайн» | `settings.json` |
| «Раздать всё это команде одним пакетом» | плагин + маркетплейс |
| «Дать доступ к внешней системе» | MCP-сервер |

Ключевой водораздел: **скил — рекомендация модели, хук — исполнение харнессом.**
Если требование звучит «каждый раз», «обязательно», «запрети» — это хук, а не капслок в скиле.

---

## 1. Скил

`.claude/skills/<имя>/SKILL.md` (проект) · `~/.claude/skills/<имя>/SKILL.md` (личный) ·
`<plugin>/skills/<имя>/SKILL.md` (плагин). Полный контракт полей — [frontmatter.md](frontmatter.md).

Канонический состав каталога (соглашение из спеки и из официального `skill-creator`):

```
skill-name/
├── SKILL.md      # обязателен: метаданные + инструкции
├── scripts/      # исполняемый код для детерминированных/повторяющихся операций
├── references/   # документация, подгружаемая в контекст по необходимости
└── assets/       # то, что попадает в результат: шаблоны, иконки, шрифты
```

Прогрессивное раскрытие — три уровня:
1. **Метаданные** (`name` + `description`, ~100 токенов) — в системном промпте всегда, для всех скилов.
2. **Тело SKILL.md** — грузится при активации. Ориентир: **< 500 строк и < 5000 токенов**.
3. **Вложенные файлы** — читаются по требованию; объём практически не ограничен, скрипты
   вообще могут исполняться без загрузки в контекст.

Правила для вложенных файлов:
- В теле пиши **условие загрузки**, а не «см. подробности»: «прочитай `references/api-errors.md`,
  если API вернул не-200» работает, «see references/ for details» — нет.
- Ссылки — относительные от корня скила, максимум один уровень вложенности цепочки ссылок.
- Для справочника > 300 строк добавь в его начало оглавление.
- Взаимоисключающие сценарии разноси по разным файлам — это экономит токены.

`.claude/commands/имя.md` — старый формат слэш-команд, поддерживает тот же frontmatter,
но не умеет вспомогательные файлы. Новое пишем скилами; при конфликте имён выигрывает скил.

---

## 2. Субагент

`.claude/agents/<имя>.md`. Тело файла = **системный промпт** агента; задачу он получает
из делегирующего сообщения.

Поля frontmatter (обязательны только `name` и `description`):
`name`, `description`, `tools`, `disallowedTools`, `model`, `permissionMode`, `maxTurns`,
`skills`, `mcpServers`, `hooks`, `memory`, `background`, `effort`, `isolation`, `color`, `initialPrompt`.

- `name` — строчные буквы и дефисы; `:` запрещён (зарезервирован под неймспейс плагинов).
- `tools` — если опущено, наследует все доступные сабагентам инструменты.
  Чтобы **преднагрузить скилы, используй `skills`, а не перечисление `Skill` в `tools`**.
- `skills` — в контекст на старте инжектится **полное тело** перечисленных скилов, не описание.
  Нельзя преднагрузить скил с `disable-model-invocation: true` (включая встроенный `/verify`);
  отсутствующий или выключенный скил пропускается с записью в debug-лог. Встроенные агенты
  (Explore, Plan) преднагрузку не делают. Список не ограничивает доступ — остальные скилы
  агент всё равно может вызвать через Skill tool; полный запрет — убрать `Skill` из `tools`.
- `model` — `sonnet` / `opus` / `haiku` / `fable` / полный id / `inherit` (по умолчанию `inherit`).
- `permissionMode` — `default`, `acceptEdits`, `auto`, `dontAsk`, `bypassPermissions`, `plan`, `manual`.
- `isolation: worktree` — своя git-worktree; `memory` — `user|project|local`.

```yaml
---
name: api-developer
description: Implement API endpoints following team conventions
skills:
  - api-conventions
  - error-handling-patterns
---

Implement API endpoints. Follow the conventions and patterns from the preloaded skills.
```

Две стороны связки скил↔субагент:

| Подход | Системный промпт | Задача | Что ещё грузится |
| --- | --- | --- | --- |
| Скил с `context: fork` | из типа агента | тело SKILL.md | CLAUDE.md (кроме Explore/Plan) |
| Субагент с `skills:` | тело файла агента | сообщение-делегирование | тела преднагруженных скилов + CLAUDE.md |

В плагинах агентам доступно только подмножество полей: `name`, `description`, `model`, `effort`,
`maxTurns`, `tools`, `disallowedTools`, `skills`, `memory`, `background`, `isolation`.
`hooks`, `mcpServers` и `permissionMode` у плагинных агентов запрещены из соображений безопасности.

---

## 3. Хуки

Три места объявления: `settings.json`, frontmatter субагента, frontmatter скила.
В скиле и агенте хуки живут ровно столько, сколько активен компонент, и снимаются по завершении.
Поддерживаются **все события**; у субагентов `Stop` автоматически превращается в `SubagentStop`.

```yaml
---
name: secure-operations
description: Perform operations with security checks
hooks:
  PreToolUse:
    - matcher: "Bash"
      hooks:
        - type: command
          command: "./scripts/security-check.sh"
---
```

Форма: `hooks:` → имя события → список `{matcher, hooks: [обработчики]}`.

Типы обработчиков: `command`, `http`, `mcp_tool`, `prompt`, `agent`.
Общие поля: `type` (обязателен), `if` (фильтр по правилу разрешений; учитывается только на
`PreToolUse`, `PostToolUse`, `PostToolUseFailure`, `PermissionRequest`, `PermissionDenied`),
`timeout` (по умолчанию 600 с для command/http/mcp_tool, 30 для prompt, 60 для agent),
`statusMessage`, `once` (сработать один раз за сессию и сняться — **учитывается только в
frontmatter скила**, в settings и у агентов игнорируется).
У `command` дополнительно: `command`, `args` (exec-форма, без шелла), `async`, `asyncRewake`,
`shell` (`bash`|`powershell`).

События: `SessionStart`, `Setup`, `InstructionsLoaded`, `UserPromptSubmit`, `UserPromptExpansion`,
`MessageDisplay`, `PreToolUse`, `PermissionRequest`, `PostToolUse`, `PostToolUseFailure`,
`PostToolBatch`, `PermissionDenied`, `Notification`, `SubagentStart`, `SubagentStop`,
`TaskCreated`, `TaskCompleted`, `Stop`, `StopFailure`, `TeammateIdle`, `ConfigChange`,
`CwdChanged`, `DirectoryAdded`, `FileChanged`, `WorktreeCreate`, `WorktreeRemove`,
`PreCompact`, `PostCompact`, `SessionEnd`, `Elicitation`, `ElicitationResult`.

Хуки из frontmatter проектного компонента запускаются только после принятия trust-диалога
на соответствующий каталог. `hooks` — поле Claude Code, в портируемой спеке его нет.

---

## 4. Плагин и маркетплейс

```
my-plugin/
├── .claude-plugin/plugin.json     # манифест (обязателен только `name`)
├── skills/<имя>/SKILL.md
├── agents/*.md
├── hooks/
└── .mcp.json
```

- Все каталоги — **в корне плагина**, а не внутри `.claude-plugin/`.
- Если нет каталога `skills/` и нет поля `skills` в манифесте, `SKILL.md` в корне плагина
  грузится как один скил (с v2.1.142). В этом случае задай frontmatter `name`: иначе имя
  возьмётся из каталога установки, а у маркетплейсных плагинов это версия, меняющаяся при обновлении.
- `skills` — единственное поле путей, которое **добавляет** к дефолту: `skills/` сканируется
  всегда, перечисленные каталоги грузятся дополнительно. `commands`, `agents`, `workflows`,
  `outputStyles` — заменяют дефолт.
- Пути относительные и начинаются с `./`; `skills` дополнительно принимает `"."`.
- `CLAUDE.md` в корне плагина **не грузится** — инструкции отдавай скилом.

```json
{
  "name": "quality-review-plugin",
  "description": "Adds a quality-review skill for quick code reviews",
  "version": "1.0.0",
  "author": { "name": "Your Name" }
}
```

Маркетплейс — `<marketplace>/.claude-plugin/marketplace.json`:

```json
{
  "name": "my-plugins",
  "owner": { "name": "Your Name" },
  "plugins": [
    {
      "name": "quality-review-plugin",
      "source": "./plugins/quality-review-plugin",
      "description": "Adds a quality-review skill for quick code reviews"
    }
  ]
}
```

Установка: `/plugin marketplace add ./my-marketplace` → `/plugin install quality-review-plugin@my-plugins`.
Вызов скила: `/quality-review-plugin:quality-review`. Проверка: `claude plugin validate ./my-plugin --strict`.

**Skills-directory плагин**: любая папка внутри каталога скилов, содержащая
`.claude-plugin/plugin.json`, грузится как плагин `<name>@skills-dir` со следующей сессии —
без маркетплейса и установки. Так скил дотягивает до себя хуки, агентов и MCP.
`~/.claude/skills/` — личная область, `<cwd>/.claude/skills/` — проектная (только после trust,
и вверх по дереву не поднимается). Правки `SKILL.md` применяются сразу, а `hooks/`, `.mcp.json`,
`agents/`, `output-styles/` требуют `/reload-plugins`.

Переменные: `${CLAUDE_PLUGIN_ROOT}` (каталог установки, меняется при обновлении — состояние туда
не пишем), `${CLAUDE_PLUGIN_DATA}` (переживает обновления), `${CLAUDE_PROJECT_DIR}`.

---

## 5. Скрипты внутри скила

Скрипт оправдан, когда модель раз за разом переизобретает одну и ту же логику,
либо когда операция должна быть детерминированной.

Жёсткие требования к скрипту, который запускает агент:
- **Никаких интерактивных запросов** — среда исполнения агента их не переживает.
- `--help` с описанием; понятные сообщения об ошибках («ожидалось X, получено Y»).
- Данные в **stdout**, диагностика в **stderr**; структурированный вывод (JSON/CSV/TSV).
- Идемпотентность, `--dry-run` для разрушающих операций, осмысленные коды возврата.
- **Предсказуемый объём вывода**: харнессы обрезают вывод инструмента примерно на 10–30 тыс. символов.
- Зависимости — самодостаточно и с прикреплённой версией: PEP 723 (`# /// script` + `uv run`),
  `npx`/`bunx`/`deno run` с пином версии; требования к среде — в `compatibility` или в теле скила.
- Путь к скрипту в теле и в `allowed-tools` — через `${CLAUDE_SKILL_DIR}`, тогда запуск не спросит прав.

---

## 6. Настройки, которые чаще всего нужны рядом со скилами

| Ключ | Зачем |
| --- | --- |
| `skillOverrides` | видимость скила без правки его frontmatter: `on` / `name-only` / `user-invocable-only` / `off` |
| `skillListingBudgetFraction` | доля контекста под листинг описаний (по умолчанию 1%) |
| `skillListingMaxDescChars` | предел одной записи листинга (по умолчанию 1536) |
| `disableSkillShellExecution` | запретить `` !`cmd` `` инъекции в пользовательских скилах |
| `permissions.deny: ["Skill"]` | запретить модели вызывать скилы вообще; точечно — `Skill(name)`, `Skill(name *)` |

`.claude/settings.json` — командное, под git. `.claude/settings.local.json` — личное, в `.gitignore`.
Добавь `"$schema": "https://json.schemastore.org/claude-code-settings.json"` — редакторы начнут
подсказывать и валидировать ключи.

### Синтаксис правил разрешений (там, где чаще всего ошибаются)

- `Bash(npm run build)` — точное совпадение; `Bash(npm run test *)` — префикс;
  `Bash(ls:*)` — то же самое, что `Bash(ls *)`, но `:*` работает **только в конце** паттерна.
- Пробел перед `*` даёт границу слова: `Bash(ls *)` матчит `ls -la`, но не `lsof`;
  `Bash(ls*)` матчит оба.
- Составные команды разбираются по операторам `&&`, `||`, `;`, `|`, `|&`, `&`, перевод строки —
  правило должно покрывать **каждую** подкоманду.
- Обёртки `timeout`, `time`, `nice`, `nohup`, `stdbuf`, `command`, `builtin`, `noglob`, голый `xargs`
  снимаются перед матчингом. А вот `npx`, `docker exec`, `devbox run`, `mise exec` — нет:
  `Bash(devbox run *)` разрешает вообще что угодно внутри. Пиши правило вместе с внутренней командой.
- `watch`, `setsid`, `ionice`, `flock`, `find -exec/-delete` префиксным правилом не покрываются — всегда спросят.
- Нельзя матчить основное поле инструмента: `Bash(command:rm *)` игнорируется с предупреждением
  при старте. Правильно — `Bash(rm *)`, `Read(./path)`, `WebFetch(domain:host)`.
- `WebFetch(domain:*.example.com)` — любой поддомен, но не сам `example.com`.
- `Skill(name)` — точное совпадение, `Skill(name *)` — с любыми аргументами, голый `Skill` в deny
  убирает вызов скилов у модели целиком.
- Подстановка `${CLAUDE_PROJECT_DIR}` в правилах `settings.json` **не документирована** —
  в отличие от `allowed-tools` в frontmatter скила, где она работает. В settings пиши путь как есть.

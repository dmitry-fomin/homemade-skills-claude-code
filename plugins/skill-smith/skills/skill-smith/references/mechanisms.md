# Механизмы расширения Claude Code: что выбрать и как это выглядит на диске

Сверено 2026-09-12 на Claude Code 2.1.269 по code.claude.com/docs/en/{skills,hooks,sub-agents,
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

Поля frontmatter (обязательны только `name` и `description`), полный список:
`name`, `description`, `tools`, `disallowedTools`, `model`, `permissionMode`, `maxTurns`,
`skills`, `mcpServers`, `hooks`, `memory`, `background`, `effort`, `isolation`, `color`,
`initialPrompt`, `experimental`.

- `name` — строчные буквы и дефисы; `:` запрещён (зарезервирован под неймспейс плагинов), файл
  с таким именем не грузится вовсе (до v2.1.218 принимался). Имя файла совпадать не обязано.
  Хуки получают это значение как `agent_type`.
- `tools` — если опущено, наследует все доступные сабагентам инструменты.
  Чтобы **преднагрузить скилы, используй `skills`, а не перечисление `Skill` в `tools`**.
- `skills` — в контекст на старте инжектится **полное тело** перечисленных скилов, не описание.
  Нельзя преднагрузить скил с `disable-model-invocation: true` (включая встроенный `/verify`);
  отсутствующий или выключенный скил пропускается с записью в debug-лог. Встроенные агенты
  (Explore, Plan) преднагрузку не делают. Список не ограничивает доступ — остальные скилы
  агент всё равно может вызвать через Skill tool; полный запрет — убрать `Skill` из `tools`.
- `model` — `sonnet` / `opus` / `haiku` / `fable` / полный id (`claude-opus-5`) / `inherit`.
  Порядок разрешения: параметр `model` конкретного вызова → frontmatter → `CLAUDE_CODE_SUBAGENT_MODEL`
  → модель основной беседы (до v2.1.251 переменная шла первой и перебивала всё, включая `inherit`).
  `CLAUDE_CODE_SUBAGENT_MODEL_FORCE=1` (v2.1.257+) игнорирует `model` всех определений.
- `effort` — `low|medium|high|xhigh|max`, перебивает effort сессии, по умолчанию наследует.
  **Задаётся только во frontmatter (или в JSON `--agents`): у инструмента Agent параметра
  `effort` нет — на вызов можно передать лишь `model`.**
- `permissionMode` — `default`, `acceptEdits`, `auto`, `dontAsk`, `bypassPermissions`, `plan`,
  `manual` (алиас `default`, v2.1.200+).
- `isolation: worktree` — своя git-worktree (единственное допустимое значение); `memory` — `user|project|local`.
- `experimental` — карта; ключ `cacheTtl` (`5m`|`1h`) выбирает время жизни prompt-кэша для запросов
  этого сабагента (v2.1.248+). Пишется **внутрь** `experimental`, не на верхний уровень; читается
  только из файлов сабагентов, прочие значения игнорируются.
- `color` — `red|blue|green|yellow|purple|orange|pink|cyan`, цвет в списке задач и транскрипте.
- `initialPrompt` — автоотправляется первым ходом, когда агент запущен как главный (`--agent`
  или настройка `agent`); команды и скилы в нём раскрываются, к промпту пользователя приклеивается спереди.

Флаг `--agents` принимает JSON: поле `prompt` (системный промпт вместо тела файла) плюс
`description`, `tools`, `disallowedTools`, `model`, `permissionMode`, `mcpServers`, `hooks`,
`maxTurns`, `skills`, `initialPrompt`, `memory`, `effort`, `background`, `isolation`.

Файл сабагента **молча пропускается** (причина — в `--debug`-лог), если нет `name`, нет
`description` при наличии `name`, открывающий `---` не на первой строке, `name` начинается с `-`
или содержит `:`, либо YAML не парсится. У **плагинных** агентов иначе: без `name` или с битым
YAML агент всё равно грузится под именем файла.

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
Поддерживаются **все события**; у субагентов `Stop` автоматически превращается в `SubagentStop`.

Живучесть разная, и это легко перепутать:
- **хуки субагента** работают только пока бежит этот субагент и снимаются по завершении;
- **хуки скила** регистрируются при вызове скила и **живут до конца сессии**, срабатывая и в
  последующих ходах. Снять после первого успешного срабатывания — `once: true`.

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
`PreCompact`, `PostCompact`, `PreModelSwitch`, `PostModelSwitch`, `SessionEnd`,
`Elicitation`, `ElicitationResult`.

`PreModelSwitch` / `PostModelSwitch` — до и после смены модели в сессии (первое может
заблокировать смену); на входе вместо `model` приходят `from_model` и `to_model`.

Общие поля входа: `session_id`, `prompt_id`, `transcript_path`, `cwd`, `scratchpad_dir`
(v2.1.257+), `permission_mode`, `effort` (объект с `level`), `hook_event_name`. Внутри
сабагента или при `--agent` добавляются `agent_id` и `agent_type`.

Trust-диалог гейтит хуки **неодинаково**:
- хуки во frontmatter **проектного субагента** запускаются только после принятия trust-диалога
  на каталог, откуда взят файл агента; `-p`-сессия за принятие не считается (до v2.1.218 запускались и без);
- хуки во frontmatter **проектного скила** — как и `allowed-tools` — регистрируются при вызове
  скила даже в недоверенной папке и в `-p`-прогоне.

`hooks` — поле Claude Code, в портируемой спеке его нет.

### `PermissionRequest` — автоодобрение прав

Событие существует. Срабатывает, когда харнесс собирается спросить разрешение на инструмент;
матчится по имени инструмента, как `PreToolUse`. В сессиях, где спросить нельзя (фоновые
сабагенты в `-p`), хуки всё равно запускаются, и **если ни один не вернул решение, вызов
запрещается**. Ни `PreToolUse`, ни `PermissionRequest` не срабатывают на `EndConversation`
и на сетевой запрос sandbox-команды.

Вход: общие поля + `tool_name`, `tool_input` (как у `PreToolUse`, но **без `tool_use_id`) и
необязательный массив `permission_suggestions` с предлагаемыми permission-апдейтами. `agent_type`
приезжает как общее поле — когда хук сработал внутри сабагента (плюс `agent_id`).

Ответ — `decision` внутри `hookSpecificOutput`:

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PermissionRequest",
    "decision": { "behavior": "allow", "updatedInput": { "command": "npm run lint" } }
  }
}
```

| Поле `decision` | Смысл |
| --- | --- |
| `behavior` | `allow` / `deny`. `allow` **не перебивает** совпавшее deny- или ask-правило — они всё равно вычисляются |
| `updatedInput` | только с `allow`: подменяет вход инструмента **целиком**, неизменные поля тоже перечисли; результат заново проверяется deny/ask-правилами |
| `updatedPermissions` | только с `allow`: массив permission-апдейтов (`addRules`, `replaceRules`, `removeRules`, `setMode`, `addDirectories`, `removeDirectories`) с `destination` — `session`, `localSettings`, `projectSettings`, `userSettings` |
| `message` | только с `deny`: причина для модели |
| `interrupt` | только с `deny`: `true` останавливает Клода |

Выход 2 **без** объекта `decision` ничего не меняет, stderr выбрасывается: разрешить или
запретить может только `decision`.

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

- Манифест **опционален**: без него компоненты ищутся в дефолтных местах, имя плагина берётся
  из имени каталога. Манифест нужен под метаданные и нестандартные пути. С манифестом обязателен
  только `name`. Нераспознанные поля верхнего уровня игнорируются (`claude plugin validate` даёт
  warning, `--strict` превращает warning в ошибку); у распознанного поля с неверным типом плагин
  обычно не грузится вообще — кроме `experimental` и `metadata`, где не-объект просто игнорируется.
- Все каталоги — **в корне плагина**, а не внутри `.claude-plugin/`.
- Если нет каталога `skills/` и нет поля `skills` в манифесте, `SKILL.md` в корне плагина
  грузится как один скил (с v2.1.142). В этом случае задай frontmatter `name`: иначе имя
  возьмётся из каталога установки, а у маркетплейсных плагинов это версия, меняющаяся при обновлении.
- `skills` — единственное поле путей, которое **добавляет** к дефолту: `skills/` сканируется
  всегда, перечисленные каталоги грузятся дополнительно. `commands`, `agents`, `workflows`,
  `outputStyles`, `experimental.themes`, `experimental.monitors` — заменяют дефолт.
  У `hooks`, `mcpServers`, `lspServers` свои правила слияния.
  Исключение для `skills`: если `source` маркетплейсной записи указывает в корень маркетплейса,
  перечисление конкретных подкаталогов дефолтный скан **заменяет**.
- Пути относительные и начинаются с `./`; `skills` дополнительно принимает `"."` (до v2.1.221
  `"."` ломал валидацию — для совместимости пиши `"./"`).
- Поля манифеста: `name`, `displayName`, `version`, `description`, `author`, `homepage`,
  `repository`, `license`, `keywords`, `metadata`, `defaultEnabled`, `$schema`; пути —
  `skills`, `commands`, `agents`, `workflows`, `hooks`, `mcpServers`, `outputStyles`,
  `lspServers`, `experimental.{themes,monitors,evals}`; плюс `userConfig`, `channels`,
  `dependencies` (список плагинов, можно с semver-констрейнтом).
- `defaultEnabled: false` — плагин ставится выключенным. Перебивается записью в `enabledPlugins`
  на любом уровне настроек и одноимённым полем в записи маркетплейса.
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
`~/.claude/skills/` — личная область без ограничений, `<cwd>/.claude/skills/` — проектная: только
после trust-диалога, и грузится **лишь из основного рабочего каталога сессии** — вверх до корня
репозитория, в отличие от обычных скилов, не поднимается (запускай из корня или переезжай
`/cd`, v2.1.246+). У проектной области код дополнительно урезан: MCP-серверы проходят
то же поштучное одобрение, что проектный `.mcp.json`, LSP стартуют только после trust,
фоновые мониторы не грузятся вовсе. Правки `SKILL.md` применяются сразу, а `hooks/`, `.mcp.json`,
`agents/`, `output-styles/` требуют `/reload-plugins`. Снять такой плагин — удалить папку или
`claude plugin disable <имя>@skills-dir`; шага uninstall нет, ничего не устанавливалось.

Переменные: `${CLAUDE_PLUGIN_ROOT}` (каталог установки, меняется при обновлении — состояние туда
не пишем), `${CLAUDE_PLUGIN_DATA}` (переживает обновления, создаётся при первом обращении),
`${CLAUDE_PROJECT_DIR}`. Все три экспортируются в процессы хуков и в подпроцессы MCP/LSP-серверов
как обычные env-переменные (`CLAUDE_PLUGIN_ROOT` и т. д.) — независимо от формы запуска хука.

### `userConfig` — значения, которые спрашивают у пользователя

Объявляется в `plugin.json` картой «ключ → описание опции»; Claude Code спрашивает их при
включении плагина, руками править `settings.json` не надо. Ключи — валидные идентификаторы.

```json
{
  "userConfig": {
    "api_token": {
      "type": "string",
      "title": "API token",
      "description": "API authentication token",
      "sensitive": true
    }
  }
}
```

Поля опции: `type` (обяз., `string|number|boolean|directory|file`), `title` (обяз.),
`description` (обяз.), `sensitive`, `required`, `default`, `multiple` (массив строк для `string`),
`min`/`max` (для `number`).

**Как значение доезжает в хук:**
- `${user_config.KEY}` — подстановка в конфигах MCP/LSP-серверов и в командах хуков, **но только
  в exec-форме** (когда задан `args`); несекретные значения подставляются ещё в тела скилов и агентов.
- `CLAUDE_PLUGIN_OPTION_<KEY>` (ключ в верхнем регистре) — env-переменная в процессе хука.
  Все значения, включая секретные, экспортируются так.
- Shell-форма хука с `${user_config.*}` в `command` **падает с ошибкой**, а не подставляет
  (до v2.1.207 подставляла): значение попало бы в шелл. Варианты — перейти на exec-форму с `args`
  или читать `$CLAUDE_PLUGIN_OPTION_<KEY>`. Так же отвергают `${user_config.*}` команды мониторов
  и MCP `headersHelper` — там значение читают из конфиг-файла в самом скрипте.

Несекретные значения лежат в `pluginConfigs[<plugin-id>].options` пользовательского
`settings.json`; секретные — в Keychain (macOS, лимит ~2 КБ вместе с OAuth-токенами) или
в `~/.claude/.credentials.json`. `pluginConfigs` читается **только** из пользовательских
настроек, `--settings` и managed-настроек; записи в `.claude/settings.json` и
`.claude/settings.local.json` проекта **игнорируются** (до v2.1.207 читались) — иначе
клонированный репозиторий подсунул бы значения в команды хуков. На `enabledPlugins`
это ограничение не распространяется.

`channels` — объявление каналов инжекта сообщений (Telegram/Slack/Discord-подобных); обязательное
поле `server` должно совпадать с ключом в `mcpServers` плагина, а необязательный
per-channel `userConfig` использует ту же схему, что и верхнеуровневый.

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

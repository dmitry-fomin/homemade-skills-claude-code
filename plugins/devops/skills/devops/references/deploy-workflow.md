# Workflow деплоя

Раннер `self-hosted` живёт на том же хосте, что и стэки. Деплой — это не «доставить артефакт на
удалённую машину», а «положить файлы в соседний каталог и перезапустить compose». Отсюда все
особенности ниже.

Имя стэка задаётся через `env: STACK:` и **не обязано совпадать с именем репозитория**.

## Канон A: образ собирается в CI

Признак — в репе есть `build-*-image.yml` или в compose стоит `image: ghcr.io/...`.

Сборка идёт на обычном GitHub-раннере (`ubuntu-latest`) и пушится в registry; прод только
забирает готовое. Так деплой перестаёт зависеть от доступности apt-зеркал с сервера.

```yaml
- name: Login to registry
  run: echo "${{ secrets.GITHUB_TOKEN }}" | docker login ghcr.io -u "${{ github.actor }}" --password-stdin

- name: Up
  run: |
    cd "/opt/stacks/${STACK}"
    docker compose pull
    docker compose up -d --remove-orphans
    docker image prune -f
```

`--build` здесь не нужен и не добавляется: образ уже собран. Код, который всё же едет rsync-ом
(конфиги, шаблоны), синхронизируется отдельным шагом по правилам ниже.

## Канон B: сборка на проде

Признак — ни `build-*-image.yml`, ни `ghcr.io` в репе нет.

```yaml
name: Deploy
on:
  push:
    branches: [main]

env:
  STACK: example.com

jobs:
  deploy:
    runs-on: [self-hosted, linux, x64, docker, prod]
    steps:
      - uses: actions/checkout@v4

      - name: Sync code
        run: |
          STACK_DIR="/opt/stacks/${STACK}"
          mkdir -p "${STACK_DIR}"
          rsync -rlptD --delete \
            --exclude='.env' \
            --exclude='.git' \
            --exclude='node_modules/' \
            --exclude='vendor/' \
            --exclude='uploads/' --exclude='media/' \
            --exclude='cache/' --exclude='logs/' --exclude='sess/' \
            ./ "${STACK_DIR}/"

      - name: Up
        run: |
          cd "/opt/stacks/${STACK}"
          docker compose pull --ignore-pull-failures || true
          docker compose up -d --build --remove-orphans
          docker image prune -f

      - name: Verify
        run: |
          sleep 10
          cd "/opt/stacks/${STACK}"
          docker compose ps
          ! docker compose ps --format json | jq -e '.[] | select(.State != "running")' > /dev/null
```

Шаг Verify обязателен: без него `up -d` считается успешным, даже когда контейнер сразу упал в
рестарт-петлю, и workflow зеленеет на сломанном деплое.

## Флаги rsync

`-a` тянет за собой сохранение owner/group. Раннер работает не от root и не может сделать `chgrp`
на файле, принадлежащем процессу контейнера — падает с `chgrp: Operation not permitted`.

- Есть каталоги под чужим uid (PHP-стэки с runtime-каталогами, файлы, once правленные на сервере
  руками) → **`-rlptD`**.
- Нет (Node-сервис, статика, бот) → `-a`/`-av` работает и переписывания не требует.

## Каждый `--exclude` — за что отвечает

| Строка | Что случится без неё |
| --- | --- |
| `.env` | **`--delete` сотрёт секреты стэка.** Контейнеры не поднимутся, восстанавливать руками |
| `.git` | в каталог стэка уезжает история репозитория |
| `node_modules/`, `vendor/` | долгая синхронизация и рассинхрон с тем, что ставит сборка |
| `uploads/`, `media/`, альбомы | **пользовательский контент стирается** — его нет в git |
| `cache/`, `logs/`, `sess/`, скомпилированные шаблоны | создано процессом контейнера под чужим uid, `--delete` спотыкается о права |
| per-stack тема или ассеты, живущие только на сервере | при первом же деплое сносятся |

**Что исключать нельзя:** всё, что собрано на раннере шагом выше. У SPA `dist/` (или `.output/`)
обязан уехать — исключишь, и на сервер приедет пустой сайт.

Для не-PHP проекта копировать список целиком не нужно: оставляй релевантные строки.

## `.env`

Кладётся руками один раз, до первого прогона workflow:

```bash
ssh deploy@<host>
mkdir -p /opt/stacks/<stack>
nano /opt/stacks/<stack>/.env
chmod 600 /opt/stacks/<stack>/.env
```

Workflow его не подкладывает и не перезаписывает. `secrets.ENV_FILE` и подобное — не наш способ:
секрет, прошедший через CI, оседает в логах и в истории.

## Миграции

Механизм у каждого стэка свой, и он определяется по репе, а не по привычке:

| Что видно в репе | Как запускается |
| --- | --- |
| одноразовый сервис `migrate` в compose | остальные ждут его через `condition: service_completed_successfully` |
| Alembic / Django | отдельный шаг workflow после `up`: `docker compose exec -T <svc> alembic upgrade head` |
| `.sql` в `config/sql/` | применяются вручную клиентом в контейнере, автоматики нет |
| ничего из этого | миграций нет, схемой владеет CMS |

**Только вперёд.** `downgrade` из workflow не запускается никогда: откат схемы на живых данных —
решение человека, а не шага пайплайна.

## Откат

В каноне B готового образа для отката нет: откат — это `git revert` и повторная сборка.
Планируя рискованное изменение, скажи об этом человеку заранее, а не после.

Отдельная беда канона B — **build cache растёт на проде** и однажды кладёт деплой с
`No space left on device`. Штатная чистка: `docker system prune -af --filter until=168h`.
**Без `--volumes`** — с ним наблюдалось удаление именованных томов с живыми данными.

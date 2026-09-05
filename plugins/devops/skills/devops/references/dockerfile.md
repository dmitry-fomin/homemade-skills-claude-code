# Dockerfile: шаблоны и грабли

## Общее для всех Debian-образов

`deb.debian.org` за Fastly недоступен из РФ. Симптом — не ошибка, а **зависший `apt-get update`**
до таймаута сборки. Поэтому первой инструкцией после `FROM`:

```dockerfile
# bookworm/trixie — новый формат sources
RUN sed -i 's|http://deb.debian.org|http://mirror.yandex.ru|g' /etc/apt/sources.list.d/debian.sources
# bullseye и старше — старый формат
# RUN sed -i 's|http://deb.debian.org|http://mirror.yandex.ru|g' /etc/apt/sources.list
```

Alpine-образам это не нужно. IPv6 на хосте выключен глобально — если outbound из build-стадии
всё равно висит, причина обычно там же, а не в Dockerfile.

Именно эта возня — главный довод за то, чтобы собирать образ в CI на GitHub-раннере и приезжать
на прод готовым (см. [deploy-workflow.md](deploy-workflow.md)).

## Node

```dockerfile
FROM node:22-alpine AS deps
WORKDIR /app
COPY package*.json ./
RUN npm ci                       # ВСЕ зависимости: сборке нужны dev

FROM node:22-alpine AS build
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
RUN addgroup -S app && adduser -S app -G app
COPY --from=build --chown=app:app /app/dist ./dist
COPY --from=build --chown=app:app /app/package*.json ./
RUN npm ci --omit=dev && npm cache clean --force
USER app
EXPOSE 3000
# wget есть в busybox alpine; curl — нет
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD wget -qO- http://127.0.0.1:3000/health || exit 1
CMD ["node", "dist/main.js"]
```

Две ошибки, которые ломают сборку и живут во всех типовых шаблонах:

- **`npm ci --omit=dev` (или `--only=production`) до `npm run build`.** Сборке нужны dev-зависимости;
  прод-набор ставится в финальной стадии, а не в первой.
- **`USER nonroot` в образе, где такого пользователя нет.** В `node:*-alpine`, `python:*-slim`,
  `php:*-bookworm` его нет — контейнер упадёт при старте. Пользователя создаёшь сам.

## PHP-FPM

```dockerfile
FROM php:8.4-fpm-bookworm
RUN sed -i 's|http://deb.debian.org|http://mirror.yandex.ru|g' /etc/apt/sources.list.d/debian.sources
RUN apt-get update && apt-get install -y --no-install-recommends \
      libzip-dev libpng-dev libicu-dev \
 && docker-php-ext-install -j"$(nproc)" pdo_mysql zip gd intl opcache \
 && apt-get purge -y libzip-dev libpng-dev libicu-dev \
 && rm -rf /var/lib/apt/lists/*

# uid/gid внутри контейнера выравниваются с владельцем файлов стэка на хосте
RUN usermod -u 33 www-data && groupmod -g 33 www-data

WORKDIR /var/www/html
COPY --from=composer:2 /usr/bin/composer /usr/bin/composer
COPY composer.json composer.lock ./
RUN composer install --no-dev --optimize-autoloader --no-interaction \
      --no-scripts --ignore-platform-reqs
COPY --chown=www-data:www-data . .
USER www-data
```

- **`--ignore-platform-reqs` не украшение.** Образ `composer:2` собран на свежем PHP, а легаси-пакеты
  пинят `ext-* ^7.2` — без флага установка падает на несовпадении платформы.
- **`usermod -u 33`** держит владельца файлов одинаковым внутри контейнера и на хосте. Разъедется —
  и `rsync --delete` из workflow начнёт падать на правах (см. [deploy-workflow.md](deploy-workflow.md)).
- Runtime-каталоги (`cache/`, `sess/`, `logs/`, скомпилированные шаблоны) создаёт процесс
  контейнера. Они и в `.gitignore`, и в `--exclude` деплоя.

## Python

```dockerfile
FROM python:3.12-slim AS builder
RUN sed -i 's|http://deb.debian.org|http://mirror.yandex.ru|g' /etc/apt/sources.list.d/debian.sources
WORKDIR /app
COPY requirements.txt .
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt

FROM python:3.12-slim AS runner
RUN sed -i 's|http://deb.debian.org|http://mirror.yandex.ru|g' /etc/apt/sources.list.d/debian.sources
WORKDIR /app
RUN useradd -m -u 1001 app
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir /wheels/* && rm -rf /wheels
COPY --chown=app:app . .
USER app
EXPOSE 8000
# в slim нет ни curl, ни wget — проверяем средствами самого python
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health').status==200 else 1)"
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**`curl` в HEALTHCHECK slim-образа** — самая частая мёртвая проверка: команды нет, healthcheck
всегда unhealthy, контейнер бесконечно перезапускается. Либо ставь `curl` явно, либо проверяй
тем, что в образе уже есть.

## Legacy-сборки

Старый фронтенд (Webpack 4, node-sass 4) требует python2 и не собирается на современном Node.
Такое выносится в **отдельную стадию на старом базовом образе** (`node:14-bullseye-slim`),
результат копируется в основную. Тянуть весь стэк вниз ради одной стадии не нужно.

## Не от root, если есть выбор

Оговорка «если есть выбор» настоящая: `cron` в Debian обслуживает `/etc/cron.d/` только от root,
и такие сервисы легально работают рутом. Это исключение, а не разрешение — для веба, воркеров
и ботов пользователь создаётся всегда.

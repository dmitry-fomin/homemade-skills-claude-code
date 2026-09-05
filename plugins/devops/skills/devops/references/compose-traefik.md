# Compose нового сервиса и Traefik labels

## Сети

Две, и путать их нельзя:

- **внешняя сеть прокси** (обычно `traefik_proxy`, объявляется `external: true`) — только то,
  что должно быть доступно снаружи по HTTP;
- **внутренняя** (`internal`, bridge, поднимается самим стэком) — БД, кэши, воркеры, поиск.
  Наружу не смотрит вообще.

Сервис, которому нужны оба (веб-контейнер, ходящий в свою БД), состоит в двух сразу.

## Скелет стэка

```yaml
name: example

services:
  www:
    image: nginx:1.27-alpine          # минорная версия, не alpine и не latest
    restart: unless-stopped
    depends_on:
      db:
        condition: service_healthy
    networks: [proxy, internal]
    mem_limit: 512m
    volumes:
      - ./public:/var/www/html:ro
    labels:
      # см. следующий раздел
    healthcheck:
      test: ["CMD", "wget", "-qO-", "http://127.0.0.1/health"]
      interval: 30s
      timeout: 5s
      retries: 5

  db:
    image: mariadb:11.4               # LTS, минор зафиксирован
    restart: unless-stopped
    networks: [internal]              # наружу не смотрит — только internal
    mem_limit: 1g
    env_file: [.env]
    environment:
      MARIADB_DATABASE: ${DB_NAME}
      MARIADB_USER: ${DB_USER}
      MARIADB_PASSWORD: ${DB_PASSWORD}
    volumes:
      - db-data:/var/lib/mysql
    healthcheck:
      test: ["CMD", "healthcheck.sh", "--connect"]
      interval: 30s
      timeout: 5s
      retries: 5

networks:
  proxy:
    external: true
    name: traefik_proxy
  internal:
    driver: bridge

volumes:
  db-data:
```

Чего в этом файле нет и не должно быть:

- **`ports:`** — ни одной строки. Внешний трафик заходит через Traefik по labels.
  Отладочный доступ, если он реально нужен, публикуется как `"127.0.0.1:3000:3000"` и
  открывается SSH-туннелем.
- **литералов секретов** — только `${VAR}` из `.env`, лежащего рядом (`chmod 600`, в `.gitignore`).
- **`:latest`, `:alpine`, `:main`** в тегах образов — минор фиксируется явно.
- **bind-mount за пределы каталога стэка** — либо внутрь него, либо named volume.

## Labels: две пары роутеров

```yaml
labels:
  - "traefik.enable=true"
  - "traefik.docker.network=traefik_proxy"

  # ── HTTP (:80) → редирект на HTTPS ──
  - "traefik.http.routers.example-http.rule=Host(`example.com`) || Host(`www.example.com`)"
  - "traefik.http.routers.example-http.entrypoints=web"
  - "traefik.http.routers.example-http.middlewares=https-redirect@file"

  # ── HTTPS (:443) ──
  - "traefik.http.routers.example-https.rule=Host(`example.com`) || Host(`www.example.com`)"
  - "traefik.http.routers.example-https.entrypoints=websecure"
  - "traefik.http.routers.example-https.tls=true"
  # ЯВНО. Без этой строки прилетит production-резолвер с entrypoint.
  - "traefik.http.routers.example-https.tls.certresolver=letsencrypt-staging"
  - "traefik.http.routers.example-https.tls.domains[0].main=example.com"
  - "traefik.http.routers.example-https.tls.domains[0].sans=www.example.com"
  - "traefik.http.routers.example-https.middlewares=compress@file"

  # ── порт ВНУТРИ контейнера, не опубликованный ──
  - "traefik.http.services.example.loadbalancer.server.port=80"
```

`example` — короткое уникальное имя стэка без точек и слэшей.

### Staging → production

`letsencrypt-staging` стоит первым, пока не проверены DNS и роутинг. На staging-серте браузер
ругается — это ожидаемо. После успешной выдачи меняешь резолвер на production и передеплоиваешь.

Порядок именно такой, потому что у production-ACME жёсткие недельные лимиты: несколько неудачных
попыток на непроверенном домене выжигают их до конца недели, и сайт останется без сертификата.

### Что уже висит глобально — не дублируй

На entrypoint-ах прокси уже навешаны rate-limit, ограничение одновременных запросов и
security-заголовки. Новый сайт получает их автоматически.

- `secure-headers@file` в labels HTTPS-роутера повторять не нужно (в старых стэках он там есть —
  идемпотентно и безвредно, руками не вычищай).
- Rate-limit в labels не дублируется никогда.
- Шумная интеграция ловит 429 → её IP заносится в список исключений `sourceCriterion`,
  **глобальный лимит не повышается**.

### Canonical-редирект www → apex

Хватает двух роутеров и middleware на HTTPS-варианте, либо решается на стороне приложения.
Четыре роутера ради этого не плоди.

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
  # ЯВНО, сразу production — после предпроверки ниже. Staging не используем.
  - "traefik.http.routers.example-https.tls.certresolver=letsencrypt"
  - "traefik.http.routers.example-https.tls.domains[0].main=example.com"
  - "traefik.http.routers.example-https.tls.domains[0].sans=www.example.com"
  - "traefik.http.routers.example-https.middlewares=compress@file"

  # ── порт ВНУТРИ контейнера, не опубликованный ──
  - "traefik.http.services.example.loadbalancer.server.port=80"
```

`example` — короткое уникальное имя стэка без точек и слэшей.

### Сертификат: сразу production, после предпроверки

Staging-шаг не используется. В Traefik 3.6 смена `letsencrypt-staging` → `letsencrypt` боевой
сертификат **не выпускает**: действующий staging-серт лежит в `acme-staging.json`, Traefik отдаёт
его как подходящий для домена и новый резолвер не дёргает. Ни ошибки, ни попытки в логе. Лечится
только бэкапом и чисткой записи из `acme-staging.json` + рестартом общего прокси — все сайты хоста
лежат несколько секунд.

Лимиты Let's Encrypt бережёт не staging, а проверка до первого деплоя. Запускай **с сервера**:
на рабочей машине DNS может идти через VPN с fake-IP и врать. Для каждого домена из `Host()`,
включая `www`:

```bash
ssh deploy@<host> 'IP=<ip сервера>
for D in example.com www.example.com; do
  A=$(dig +short A $D @1.1.1.1 | grep -v "\.$" | xargs)   # CNAME-строки отбрасываем
  # --resolve: curl идёт на публичный A, а не по /etc/hosts сервера
  echo "$D  A=[$A]  AAAA=[$(dig +short AAAA $D @1.1.1.1 | grep -v "\.$" | xargs)]  HTTP=[$(curl -s -m 10 --resolve "$D:80:${A%% *}" -o /dev/null -w "%{http_code} %{remote_ip}" http://$D/.well-known/acme-challenge/precheck)]"
done'
# проходит: A=[$IP] (ровно один)  AAAA=[]  HTTP=[404 $IP]
```

AAAA должен быть пуст: при выключенном на хосте IPv6 Let's Encrypt пойдёт по AAAA и не достучится.
Не прошла — HTTPS-роутер не выкатываешь вовсе: на `websecure` production-резолвер стоит по
умолчанию, любой HTTPS-роутер сразу запросит сертификат. Выпуск всё же упал — у LE 5 неудачных
валидаций на хост в час, и Traefik сам не повторит: передеплой с теми же labels для него та же
конфигурация. Чини причину; новая попытка — при изменении labels роутера или рестарте прокси
(все сайты, с согласия человека).

Миграция с живого сервера: до DNS switchover выкатываешь только HTTP-роутер без редиректа и
проверяешь сайт по HTTP через `/etc/hosts`. HTTPS-роутер — после смены DNS и предпроверки.

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

#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "httpx>=0.27",
#   "pillow>=10.3",
#   "rembg>=2.0.59",
#   "onnxruntime>=1.18",
# ]
# ///
"""image-gen: промпт → PNG на диске, плюс обтравка готового файла.

Контракт вывода: в stdout уходит РОВНО один JSON-объект и ничего больше —
всё остальное (прогресс, предупреждения, ошибки) идёт в stderr, иначе вывод
нельзя разобрать программно.

Коды возврата: 0 — файл записан; 1 — ошибка API или фолбэк запрещён флагом;
2 — ошибка аргументов, окружения (нет ключа, нет конфига) или непредвиденный сбой.
При любой ошибке stdout остаётся пустым, а в stderr уходит строка `error: ...` —
вызывающему достаточно проверить код возврата, чтобы не парсить пустоту как JSON.

rembg объявлен зависимостью скрипта нарочно: `uv run --with rembg` тянет
зависимости минут десять при каждом вызове, а здесь окружение фиксируется
и переиспользуется из кэша uv.
"""

import argparse
import base64
import hashlib
import io
import json
import mimetypes
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

SIZES = ["1024x1024", "1024x1536", "1536x1024", "auto"]
CONF_NAME = "engines.conf"
LOG_NAME = ".image-gen.log"

REQUEST_TIMEOUT = 300.0
RETRY_STATUSES = {429, 500, 502, 503, 504}
RETRY_PAUSES = [2, 6, 14]  # повтор той же моделью — это не фолбэк
DOWNLOAD_PAUSES = [2, 6, 14]  # повтор скачивания готового кадра — генерация не повторяется

# Коды, при которых менять движок бессмысленно: это не «движок недоступен», а
# отказ по запросу, ключу или счёту. Все строки engines.conf ходят в один
# openrouter.ai с одним ключом, поэтому фолбэк на 401/402/403 не помогает в принципе.
FATAL_STATUSES = {400, 401, 402, 403, 404, 422}
FATAL_HINTS = {
    400: "Запрос отклонён — проверь --size, --prompt и референсы",
    401: "Ключ отвергнут — проверь OPENROUTER_API_KEY (объявлен в ~/.zshenv)",
    402: "Недостаточно средств на счёте OpenRouter — пополни баланс",
    403: "Доступ к модели закрыт — проверь права ключа на этот слаг",
    404: "Модель не найдена — проверь слаг в engines.conf или IMAGE_GEN_MODEL",
    422: "Запрос отклонён провайдером — проверь размер и формат референсов",
}


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def die(code: int, msg: str) -> "None":
    print(f"error: {msg}", file=sys.stderr, flush=True)
    sys.exit(code)


# --- реестр движков -------------------------------------------------------

class Engine:
    __slots__ = ("alias", "base_url", "key_var", "model", "reference")

    def __init__(self, alias, base_url, key_var, model, reference):
        self.alias = alias
        self.base_url = base_url.rstrip("/")
        self.key_var = key_var
        self.model = model
        self.reference = reference.strip().lower() in ("yes", "true", "1", "on")

    def __repr__(self):
        return f"<{self.alias} {self.model}>"


def load_engines() -> list[Engine]:
    conf = Path(__file__).resolve().parent / CONF_NAME
    if not conf.is_file():
        die(2, f"не найден реестр движков: {conf}")
    engines: list[Engine] = []
    for raw in conf.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) != 5 or not all(parts[:4]):
            log(f"warning: пропущена строка {CONF_NAME}: {raw}")
            continue
        engines.append(Engine(*parts))
    if not engines:
        die(2, f"реестр движков пуст: {conf}")
    return engines


def api_key(engine: Engine) -> str:
    key = os.environ.get(engine.key_var, "").strip()
    if not key:
        die(
            2,
            f"нет ключа: переменная {engine.key_var} не задана. "
            f"Объяви её в ~/.zshenv (export {engine.key_var}=...) и открой новую сессию. "
            "Ни одного сетевого запроса не сделано.",
        )
    return key


# --- HTTP -----------------------------------------------------------------

class ApiError(Exception):
    def __init__(self, msg: str, status: int | None = None, fatal: bool | None = None):
        super().__init__(msg)
        self.status = status
        # fatal — цепочку фолбэка продолжать нельзя: другой движок не поможет
        # (отказ по ключу/счёту/запросу) либо кадр уже сгенерирован и оплачен.
        # По умолчанию выводится из кода ответа, чтобы флаг нельзя было забыть.
        self.fatal = (status in FATAL_STATUSES) if fatal is None else fatal


def data_url(path: Path) -> str:
    if not path.is_file():
        die(2, f"референс не найден: {path}")
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def build_payload(model: str, prompt: str, size: str, refs: list[Path]) -> dict:
    payload: dict = {"model": model, "prompt": prompt, "n": 1}
    if size != "auto":
        payload["size"] = size
    if refs:
        payload["image"] = [data_url(p) for p in refs]
    return payload


def request_image(engine: Engine, model: str, payload: dict) -> tuple[str, object]:
    """Один кадр от одной модели. Повтор на 429/5xx — фолбэком не считается.

    Возвращает дескриптор кадра: ("b64", bytes) или ("url", str). Скачивание по url
    вынесено наружу нарочно — сбой загрузки не должен запускать повторную
    (платную) генерацию.
    """
    import httpx

    url = f"{engine.base_url}/images/generations"
    headers = {
        "Authorization": f"Bearer {api_key(engine)}",
        "Content-Type": "application/json",
    }
    last: Exception | None = None
    for attempt in range(len(RETRY_PAUSES) + 1):
        try:
            with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
                resp = client.post(url, headers=headers, json=payload)
            if resp.status_code in RETRY_STATUSES and attempt < len(RETRY_PAUSES):
                pause = RETRY_PAUSES[attempt]
                log(f"{model}: HTTP {resp.status_code}, повтор той же моделью через {pause} с")
                time.sleep(pause)
                continue
            if resp.status_code >= 400:
                # fatal выводится из кода: 4xx по запросу/ключу/счёту фолбэком не лечится
                raise ApiError(f"{model}: HTTP {resp.status_code}: {short(resp.text)}", resp.status_code)
            return extract_image(resp.json(), model)
        except ApiError:
            raise
        except Exception as exc:  # сеть, таймаут, битый JSON
            last = exc
            if attempt < len(RETRY_PAUSES):
                pause = RETRY_PAUSES[attempt]
                log(f"{model}: {type(exc).__name__}: {exc}; повтор через {pause} с")
                time.sleep(pause)
                continue
            raise ApiError(f"{model}: {type(exc).__name__}: {exc}") from exc
    raise ApiError(f"{model}: {last}")


def short(text: str, limit: int = 300) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit] + "…"


def extract_image(body: dict, model: str) -> tuple[str, object]:
    """Разбирает ответ API. Картинку по url здесь НЕ качаем: этот код крутится
    внутри retry-цикла генерации, и сбой загрузки стоил бы повторной генерации."""
    items = body.get("data") or []
    if not items:
        raise ApiError(f"{model}: в ответе нет поля data: {short(json.dumps(body, ensure_ascii=False))}")
    item = items[0]
    if item.get("b64_json"):
        return "b64", base64.b64decode(item["b64_json"])
    if item.get("url"):
        return "url", item["url"]
    raise ApiError(f"{model}: в ответе нет ни b64_json, ни url")


def fetch_image(url: str, model: str) -> bytes:
    """Скачивание готового кадра со своим ретраем. Кадр уже сгенерирован и оплачен,
    поэтому неудача здесь — фатальна: повторять генерацию нельзя."""
    import httpx

    last: Exception | None = None
    for attempt in range(len(DOWNLOAD_PAUSES) + 1):
        try:
            with httpx.Client(timeout=REQUEST_TIMEOUT, follow_redirects=True) as client:
                r = client.get(url)
            if r.status_code in RETRY_STATUSES and attempt < len(DOWNLOAD_PAUSES):
                pause = DOWNLOAD_PAUSES[attempt]
                log(f"{model}: загрузка кадра HTTP {r.status_code}, повтор через {pause} с")
                time.sleep(pause)
                continue
            r.raise_for_status()
            return r.content
        except Exception as exc:
            last = exc
            if attempt < len(DOWNLOAD_PAUSES):
                pause = DOWNLOAD_PAUSES[attempt]
                log(f"{model}: загрузка кадра — {type(exc).__name__}: {exc}; повтор через {pause} с")
                time.sleep(pause)
                continue
            break
    raise ApiError(
        f"{model}: кадр сгенерирован, но не скачался по url — {type(last).__name__}: {last}. "
        "Генерация уже оплачена, повторять её скрипт не станет; попробуй ещё раз вручную.",
        fatal=True,
    )


# --- запись ---------------------------------------------------------------

def to_png_bytes(raw: bytes) -> bytes:
    """Движки отдают кто PNG, кто JPEG (seedream — JPEG). На диск всегда PNG."""
    from PIL import Image

    with Image.open(io.BytesIO(raw)) as im:
        im.load()
        if im.mode not in ("RGB", "RGBA"):
            im = im.convert("RGBA" if "A" in im.getbands() else "RGB")
        buf = io.BytesIO()
        im.save(buf, format="PNG")
    return buf.getvalue()


def cut_background(png: bytes) -> bytes:
    """rembg: бинарная обтравка keep/discard. Мягкого края не даёт — см. SKILL.md."""
    from PIL import Image
    from rembg import remove

    with Image.open(io.BytesIO(png)) as im:
        out = remove(im.convert("RGBA"))
        buf = io.BytesIO()
        out.save(buf, format="PNG")
    return buf.getvalue()


def write_atomic(path: Path, payload: bytes) -> None:
    """Частично записанный файл недопустим: пишем рядом и переименовываем."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".part{os.getpid()}")
    try:
        tmp.write_bytes(payload)
        os.replace(tmp, path)  # существующий --out перезаписывается молча
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def write_log(out: Path, record: dict) -> None:
    """Строка на кадр рядом с --out: чем именно нарисован файл."""
    try:
        line = json.dumps(record, ensure_ascii=False)
        with (out.parent / LOG_NAME).open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError as exc:
        log(f"warning: не удалось записать журнал: {exc}")


# --- generate -------------------------------------------------------------

def pick_chain(engines: list[Engine], args) -> tuple[Engine, list[Engine]]:
    """Выбранный движок и хвост фолбэка — строго ВНИЗ по списку engines.conf,
    как обещают и конфиг, и SKILL.md. Новый движок в конфиге требует правки
    списка флагов здесь и в build_parser()."""
    pos = None
    for flag in ("seed", "gpt", "qwen"):
        if getattr(args, flag):
            pos = next((i for i, e in enumerate(engines) if e.alias == flag), None)
            if pos is None:
                die(2, f"движок '{flag}' не описан в {CONF_NAME}")
    if pos is None:
        pos = 0  # умолчание — первая строка конфига (seed)
    return engines[pos], engines[pos + 1:]


def cmd_generate(args) -> int:
    if args.prompt is None and args.prompt_file is None:
        die(2, "нужен --prompt или --prompt-file")
    if args.prompt is not None and args.prompt_file is not None:
        die(2, "--prompt и --prompt-file взаимоисключающие")
    if args.prompt_file is not None:
        pf = Path(args.prompt_file).expanduser()
        if not pf.is_file():
            die(2, f"файл промпта не найден: {pf}")
        prompt = pf.read_text(encoding="utf-8").strip()
    else:
        prompt = args.prompt.strip()
    if not prompt:
        die(2, "промпт пустой")
    if args.n < 1:
        die(2, "--n должен быть >= 1")

    refs = [Path(r).expanduser() for r in (args.reference or [])]
    for r in refs:
        if not r.is_file():
            die(2, f"референс не найден: {r}")

    engines = load_engines()
    chosen, rest = pick_chain(engines, args)

    # IMAGE_GEN_MODEL переопределяет слаг выбранного движка, не меняя провайдера.
    override = os.environ.get("IMAGE_GEN_MODEL", "").strip()
    requested_model = override or chosen.model

    chain: list[tuple[Engine, str]] = [(chosen, requested_model)]
    if not args.no_fallback:
        chain += [(e, e.model) for e in rest]

    out = Path(args.out).expanduser()

    if args.dry_run:
        payload = build_payload(requested_model, prompt, args.size, refs if chosen.reference else [])
        preview = dict(payload)
        if "image" in preview:
            preview["image"] = [f"<{len(refs)} референс(ов), data-url>"]
        emit({
            "path": str(out),
            "model": requested_model,
            "requested_model": requested_model,
            "fallback": False,
            "size": args.size,
            "reference_used": bool(refs) and chosen.reference,
            "transparent": bool(args.transparent),
            "dry_run": True,
            "endpoint": f"{chosen.base_url}/images/generations",
            "request": preview,
        })
        return 0

    # Метаданные собираются ПО КАЖДОМУ кадру: в серии кадры могут разъехаться
    # по моделям, и одно верхнеуровневое `model` на всю серию — это враньё.
    frames: list[dict] = []

    for idx in range(args.n):
        target = out if args.n == 1 else out.with_name(f"{out.stem}-{idx + 1}{out.suffix}")
        errors: list[str] = []
        raw: bytes | None = None
        frame_model = requested_model
        frame_refs_used = False

        for engine, model in chain:
            send_refs = refs if (refs and engine.reference) else []
            if refs and not engine.reference:
                log(
                    f"warning: движок '{engine.alias}' ({model}) не держит референс — "
                    f"--reference не передан, reference_used: false"
                )
            if engine is not chain[0][0] or model != requested_model:
                log(f"fallback: {requested_model} недоступна → пробую {model}")
            try:
                kind, value = request_image(
                    engine, model, build_payload(model, prompt, args.size, send_refs)
                )
                raw = fetch_image(value, model) if kind == "url" else value
            except ApiError as exc:
                log(f"error: {exc}")
                if exc.fatal:
                    if exc.status is None:  # сбой скачивания готового кадра — говорит сам за себя
                        die(1, str(exc))
                    parts = [f"движок '{engine.alias}' ({model}) отказал: HTTP {exc.status}"]
                    hint = FATAL_HINTS.get(exc.status)
                    if hint:
                        parts.append(hint)
                    if exc.status in (401, 402, 403):
                        parts.append(
                            "Все движки engines.conf ходят в один openrouter.ai с одним ключом, "
                            "так что подмена движка тут не помогает"
                        )
                    die(1, ". ".join(parts) + f". Ответ: {exc}")
                errors.append(str(exc))
                continue
            frame_model = model
            frame_refs_used = bool(send_refs)
            break

        if raw is None:
            frame_no = f"кадр {idx + 1}/{args.n}: " if args.n > 1 else ""
            if args.no_fallback:
                die(1, f"{frame_no}движок '{chain[0][0].alias}' ({requested_model}) не отдал кадр, "
                       "а --no-fallback запрещает подмену. " + "; ".join(errors))
            die(1, f"{frame_no}ни один движок не отдал кадр. " + "; ".join(errors))

        png = to_png_bytes(raw)
        if args.transparent:
            png = cut_background(png)
        write_atomic(target, png)
        frame = {
            "path": str(target),
            "model": frame_model,
            "fallback": frame_model != requested_model,
            "reference_used": frame_refs_used,
        }
        frames.append(frame)
        write_log(target, {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "path": frame["path"],
            "model": frame["model"],
            "requested_model": requested_model,
            "size": args.size,
            "references": [str(r) for r in refs],
            "reference_used": frame["reference_used"],
            "transparent": bool(args.transparent),
            "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16],
        })
        if frame["fallback"]:
            log(
                f"fallback: заказана {requested_model}, {frame['path']} нарисован {frame['model']}. "
                "Кадр другой модели — другая манера; для серий используй --no-fallback."
            )

    if args.n == 1:
        one = frames[0]
        result = {
            "path": one["path"],
            "model": one["model"],
            "requested_model": requested_model,
            "fallback": one["fallback"],
            "size": args.size,
            "reference_used": one["reference_used"],
            "transparent": bool(args.transparent),
        }
    else:
        # Для серии верхнеуровневая модель отсутствует нарочно: она была бы враньём.
        # `fallback: false` на верхнем уровне означает «ни один кадр не подменён» —
        # ровно то, что проверяют в приёмке серий.
        result = {
            "path": frames[0]["path"],
            "requested_model": requested_model,
            "fallback": any(f["fallback"] for f in frames),
            "size": args.size,
            "transparent": bool(args.transparent),
            "n": len(frames),
            "paths": frames,
        }
    emit(result)
    return 0


def emit(obj: dict) -> None:
    print(json.dumps(obj, ensure_ascii=False), flush=True)


# --- remove-bg ------------------------------------------------------------

def cmd_remove_bg(args) -> int:
    src = Path(args.src).expanduser()
    dst = Path(args.out).expanduser()
    if not src.is_file():
        die(2, f"файл не найден: {src}")
    try:
        same = dst.resolve() == src.resolve()
    except OSError:
        same = False
    if same:
        die(2, f"--out совпадает с --in ({src}): исходник затёрся бы обтравкой, укажи другой путь")
    png = cut_background(to_png_bytes(src.read_bytes()))
    write_atomic(dst, png)
    emit({"path": str(dst), "source": str(src), "transparent": True})
    return 0


# --- CLI ------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="generate_image.py",
        description="Генерация изображений через OpenRouter и обтравка готового файла.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser(
        "generate",
        help="промпт → PNG на диске",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Допустимые --size: 1024x1024, 1024x1536, 1536x1024, auto (умолчание 1024x1024).\n"
            "Промпт пишем по-английски: модель держит английский точнее.\n"
            "В stdout — один JSON, всё остальное в stderr."
        ),
    )
    g.add_argument("--prompt", help="текст промпта (по-английски)")
    g.add_argument("--prompt-file", help="файл с промптом — кавычки не съедаются shell'ом")
    g.add_argument("--out", required=True, help="куда положить PNG; каталоги создаются")
    g.add_argument("--size", default="1024x1024", choices=SIZES, metavar="WxH",
                   help="1024x1024 | 1024x1536 | 1536x1024 | auto")
    g.add_argument("--reference", action="append", metavar="PATH",
                   help="референсный кадр; флаг повторяемый")
    engine = g.add_mutually_exclusive_group()
    engine.add_argument("--seed", action="store_true", help="bytedance-seed/seedream-5-0-pro (умолчание)")
    engine.add_argument("--gpt", action="store_true", help="gpt-image-2 (референс не держит)")
    engine.add_argument("--qwen", action="store_true", help="qwen/qwen-image-3-pro")
    g.add_argument("--no-fallback", action="store_true", help="запретить подмену движка")
    g.add_argument("--transparent", action="store_true", help="прогнать результат через rembg")
    g.add_argument("--n", type=int, default=1, metavar="K", help="K кадров, суффиксы -1..-K")
    g.add_argument("--dry-run", action="store_true", help="напечатать запрос и модель, в API не ходить")
    g.set_defaults(func=cmd_generate)

    r = sub.add_parser("remove-bg", help="обтравка готового файла через rembg")
    r.add_argument("--in", dest="src", required=True, help="исходник")
    r.add_argument("--out", required=True, help="куда положить PNG с альфой")
    r.set_defaults(func=cmd_remove_bg)
    return parser


def main() -> int:
    """Точка входа. Ни одно исключение не должно выйти голым traceback'ом:
    вызывающий агент парсит stdout как JSON, поэтому при сбое stdout остаётся
    пустым, диагностика уходит в stderr, код возврата — 2."""
    args = build_parser().parse_args()
    try:
        return args.func(args)
    except SystemExit:
        raise  # die() уже всё напечатал
    except KeyboardInterrupt:
        print("error: прервано пользователем", file=sys.stderr, flush=True)
        return 2
    except Exception as exc:
        if os.environ.get("IMAGE_GEN_DEBUG"):
            import traceback

            traceback.print_exc()
        print(f"error: непредвиденный сбой — {type(exc).__name__}: {exc}. "
              "Подробности: IMAGE_GEN_DEBUG=1", file=sys.stderr, flush=True)
        return 2


if __name__ == "__main__":
    sys.exit(main())

# Примеры генерации для психологического проекта

Реальные промпты и референсы для создания изображений с героиней проекта.

## Референсы

### Внешность героини
`examples/mira.webp` — девушка с рыжими кудрями в мятном кардигане (лицо, волосы, стиль)

### Сцена с кресла-мешка
`examples/hero-beanbag.webp` — композиция: женщина на бежевом кресле-мешке с телефоном, фон sage green

## Финальный результат

**Команда:**
```bash
./generate_image.py generate \
  --prompt-file examples/beanbag-looking-at-phone-prompt.txt \
  --out result.png \
  --gpt \
  --reference examples/hero-beanbag.webp \
  --reference examples/mira.webp \
  --size 1024x1024
```

**Результат:** `examples/beanbag-looking-at-phone.png` (2.1 МБ, 50.7 сек)

## Эволюция промптов

### v1: Крупный план (не показано кресло целиком)
```
A woman sitting comfortably in a large cream-colored plush beanbag chair, 
holding a smartphone in her hands, looking at it with a gentle focused 
expression. She wears a mint green knitted cardigan over a gray top and 
beige comfortable pants...
```
**Проблема:** кресло обрезано, видна только часть.

### v2: Полное кресло (но смотрит в камеру)
```
Full body shot of a woman sitting comfortably in a large cream-colored 
plush beanbag chair, holding a smartphone in her hands. The entire beanbag 
chair is visible in the frame from all sides. Wide angle composition...
```
**Проблема:** женщина смотрит в камеру, а не на телефон.

### v3: Финальная версия ✅
```
Full body shot of a woman sitting comfortably in a large cream-colored 
plush beanbag chair, holding a smartphone in her hands and looking down 
at the screen with focused attention. Her head is tilted down toward the 
phone. She wears a mint green knitted cardigan over a gray top and beige 
comfortable pants. The entire beanbag chair is visible in the frame from 
all sides. Wide angle composition showing the complete round, plush beanbag. 
Soft natural lighting with a calming sage green gradient background. 
Photorealistic style, professional photography quality, warm and peaceful mood.
```

**Ключевые фразы:**
- `looking down at the screen with focused attention`
- `Her head is tilted down toward the phone`
- `The entire beanbag chair is visible in the frame from all sides`
- `Wide angle composition showing the complete round, plush beanbag`

## Выбор провайдера

| Задача | Провайдер | Время | Качество |
|--------|-----------|-------|----------|
| С референсами | CloseRouter (`--gpt`) | 41-51 сек | ✅ Отлично |
| Без референсов | A6 gpt-image-2.5 (`--a6-25`) | 40-63 сек | ✅ Хорошо |
| Без референсов, быстро | A6 gpt-image-2 (`--a6`) | 24-26 сек | ✅ Хорошо |

**Правило:** референсы = только CloseRouter. A6 с референсами даёт плохое качество.

## Структура примеров

```
examples/
├── README.md                              # этот файл
├── mira.webp                              # референс: внешность
├── hero-beanbag.webp                      # референс: сцена
├── beanbag-looking-at-phone-prompt.txt    # финальный промпт
├── beanbag-looking-at-phone.png           # результат v3 ✅
├── beanbag-full-view.png                  # результат v2
└── beanbag-with-face-ref.png              # результат v1
```

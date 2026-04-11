# СГГС: перевод по проф. Сахиб Сингху (русский)

Playwright-бот для перевода Шри Гуру Грантх Сахиб на русский язык через ChatGPT.  
Источник: [KhojGurbani](https://khojgurbani.org/) — перевод Prof. Sahib Singh (поле `sahib_singh_pa`).

**Разделение работы:**
- **Я** — анги 1–700 (ветка `sahibsingh/1-700`)
- **Коллеги** — анги 701–1430 (ветка `sahibsingh/701-1430`)

Каждый работает в своей ветке и периодически подтягивает ang_json другого человека.  
Основной артефакт — файлы `ang_json/`. Word-документ собирается из них в любой момент.

---

## Что делает бот

1. Скачивает данные анга с KhojGurbani API.
2. Отправляет в ChatGPT промпт с gurmukhi + панджабским переводом Sahib Singh.
3. Получает JSON: romanization + русский перевод построчно.
4. Сохраняет `ang_json/ang_XXXX.json`.

---

## Структура проекта

```
custom_khoj_sahib_singh/
├── chatgpt_khojgurbani_sahibsingh_bot.py   # основной скрипт
├── ang_json/                                # JSON по ангам (ang_0001.json … ang_1430.json)
├── raw_logs/                                # сырые промпты и ответы ChatGPT
├── khojgurbani_sahibsingh_chatgpt.docx      # итоговый документ (генерируется из JSON)
└── bot_profile/                             # Chrome-профиль (не коммитится)
```

### Формат ang_json

```json
{
  "ang": 1,
  "line_count": 30,
  "lines": [
    {
      "index": 1,
      "gurmukhi": "ੴ ਸਤਿ ਨਾਮੁ ...",
      "site_roman": "ik ōunkār ...",
      "sahib_singh_pa": "ਅਕਾਲ ਪੁਰਖ ਇੱਕ ਹੈ ...",
      "roman": "ik ōankār sat nām ...",
      "translation_ru": "Акал Пуракх един ..."
    }
  ]
}
```

---

## Настройка на macOS (для коллег — с нуля)

### 1. Установить Homebrew и Python

Открой **Terminal** (Finder → Программы → Утилиты → Terminal).

```bash
# Установить Homebrew (если не установлен)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Установить Python и git
brew install python git
```

### 2. Клонировать репозиторий

```bash
# Клонировать проект
git clone https://github.com/OWNER/sggs-sahib-singh.git
cd sggs-sahib-singh
```

> Замени `OWNER` на реальный логин GitHub после создания репозитория.

### 3. Переключиться на рабочую ветку

```bash
# Скачать все ветки с сервера
git fetch origin

# Переключиться на ветку для твоей части (анги 701–1430)
git checkout sahibsingh/701-1430
```

Проверь, что ты на нужной ветке:

```bash
git branch
# должна быть звёздочка напротив sahibsingh/701-1430
```

### 4. Установить зависимости

```bash
pip3 install -r requirements.txt
```

### 5. Запустить бот

```bash
# Запуск с анга 701 по 1430
python3 chatgpt_khojgurbani_sahibsingh_bot.py --start 701 --end 1430
```

При первом запуске откроется браузер. Нужно вручную войти в ChatGPT — бот дождётся.

---

## Рабочий процесс: коммит и пуш

**Главное правило:** коммитить нужно только файлы `ang_json/*.json`. Word-документ генерируется из JSON автоматически — его пушить не нужно.

### После каждой сессии работы

```bash
# 1. Посмотреть что изменилось
git status

# 2. Добавить только JSON-файлы
git add ang_json/

# 3. Сделать коммит с описанием
git commit -m "angi 701-750: perevod zakoncen"

# 4. Отправить на GitHub
git push origin sahibsingh/701-1430
```

### Если на сервере уже есть новые изменения

```bash
# Сначала подтянуть изменения
git pull origin sahibsingh/701-1430

# Затем пушить свои
git push origin sahibsingh/701-1430
```

### Конфликтов не будет

Файлы `ang_json/` называются `ang_0701.json`, `ang_0702.json` и т.д.  
Они не пересекаются с файлами другого человека (анги 1–700), поэтому конфликты при merge исключены.

---

## Параметры запуска бота

| Аргумент | По умолчанию | Описание |
|---|---|---|
| `--start` | 1 | Начальный анг |
| `--end` | 1430 | Конечный анг |
| `--output` | `khojgurbani_sahibsingh_chatgpt.docx` | Имя выходного DOCX |
| `--delay` | 3.0 | Пауза между ангами (сек) |
| `--max-retries` | 3 | Попыток на один анг |
| `--rebuild-docx-from-json` | — | Пересобрать DOCX из JSON, без ChatGPT |
| `--force-retranslate` | — | Перезаписать уже готовые JSON |
| `--reset-progress` | — | Сбросить файл прогресса |

### Продолжить с места остановки

```bash
# Бот сам определяет, какие JSON уже есть, и пропускает их.
# Просто запусти снова с тем же диапазоном:
python3 chatgpt_khojgurbani_sahibsingh_bot.py --start 701 --end 1430
```

### Пересобрать DOCX из готовых JSON (без ChatGPT)

```bash
python3 chatgpt_khojgurbani_sahibsingh_bot.py --start 1 --end 1430 --rebuild-docx-from-json
```

---

## Синхронизация в процессе работы

Каждый продолжает работать в своей ветке и периодически подтягивает ang_json другого человека — без merge и без конфликтов.

### Подтянуть новые ang.json коллег (ветка 701–1430)

```bash
# 1. Скачать последние изменения с сервера (все ветки)
git fetch origin

# 2. Скопировать только ang_json из ветки коллег в рабочую директорию
git checkout origin/sahibsingh/701-1430 -- ang_json/

# 3. Посмотреть что появилось нового
git status
# ang_json/ang_0701.json, ang_json/ang_0702.json ... — новые файлы

# 4. Если нужно — сохранить их в своей ветке
git add ang_json/
git commit -m "sync: ang_json 701-750 ot kolleg"
```

> После шага 2 файлы окажутся в твоей рабочей директории как staged changes.  
> Они не затронут твои ang_json (1–700), потому что имена файлов не пересекаются.

### Коллеги: подтянуть новые ang.json Ильи (ветка 1–700)

```bash
git fetch origin
git checkout origin/sahibsingh/1-700 -- ang_json/
git add ang_json/
git commit -m "sync: ang_json 1-100 ot Ili"
```

### Проверить прогресс друг друга (без изменений файлов)

```bash
# Сколько JSON готово у коллег:
git fetch origin
git ls-tree -r origin/sahibsingh/701-1430 --name-only | grep ang_json | wc -l
```

---

## Объединение работы (финал)

После того как оба диапазона готовы:

```bash
# На стороне владельца репо:
git checkout main
git merge sahibsingh/1-700
git merge sahibsingh/701-1430

# Пересобрать единый DOCX
python3 chatgpt_khojgurbani_sahibsingh_bot.py --start 1 --end 1430 --rebuild-docx-from-json
```

---

## Прогресс

- Всего ангов в СГГС: **1430**
- Готово: **~103** (анги 1–103, ветка `main`)
- Осталось: **~1327**

---

## Roadmap

### WordPress плагин (в разработке)

Цель: интерактивный просмотр СГГС на сайте. Функциональность:

- Листать анги (предыдущий / следующий)
- Показывать/скрывать транслитерацию
- Переключаться между переводчиками
- Адаптивная вёрстка для мобильных
- REST API на основе `ang_json/` (без базы данных, только JSON-файлы)

Структура:

```
plugin/
├── sggs-viewer.php          # основной файл плагина
├── assets/
│   ├── app.js               # Vue/vanilla JS
│   └── style.css
└── api/
    └── ang-endpoint.php     # REST endpoint: /wp-json/sggs/v1/ang/{number}
```

---

## TODO

- [ ] **WordPress плагин** — просмотр СГГС, toggle транслитерации, переключение переводчиков
- [ ] **Комментарии к Ангам и Шабдам** — просмотр комментариев (по аналогу с KhojGurbani), с возможностью переключаться между авторами (Sahib Singh, Faridkot Teeka, и др.)
- [ ] **Аудио** *(опционально)* — привязка аудиозаписей к Ангу или Шабду:
  - типы: произношение, киртан, лекция, подкаст и др.
  - несколько записей на один Анг/Шабд от разных авторов
- [ ] **Поиск** — несколько режимов:
  - по слову (панджаби / транслитерация / русский)
  - по автору (переводчик, комментатор, исполнитель)
  - по раагу
- [ ] **Поиск по словам (попап)** — кликаешь на слово на панджаби, вылетает попап:
  - буквальное значение (перевод)
  - метафорические употребления
  - примеры из Гранта
  - транслитерация
  - *(отдельное приложение, каждое слово через пробел индексируется)*
- [ ] **Словарь** — отдельная сущность на основе индекса слов (панджаби → русский + контекст)
- [ ] Перевести анги 104–700
- [ ] Перевести анги 701–1430 (коллеги)
- [ ] Merge и сборка финального DOCX

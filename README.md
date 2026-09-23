# vpnfree

Сбор VPN-ссылок (VLESS и subscription URL) из Telegram через **userbot** + управляющий бот для команд.

Структура проекта не менялась:
`main.py`, `storage.py`, `parser.py`, `interaction.py`, `orchestrator.py`, `control_bot.py`, `targets.yaml`.

> ⚠️ **Правила безопасности**
> - Значения `API_ID` / `API_HASH` / `BOT_TOKEN` / `SESSION_STRING` — только в `.env`, никогда в коде.
> - `.env`, `*.session`, `*.db` добавлены в `.gitignore` и **не должны** попадать в Git.
> - Строку сессии userbot и токен бота нельзя показывать никому: кто знает их, получает полный доступ к вашему аккаунту.
> - В логи и в чат не должны попадать VPN-ссылки: они хранятся только в SQLite (`links.db`).

---

## Установка

```bash
python -m venv venv311
venv311\Scripts\activate        # Linux/macOS: source venv311/bin/activate
pip install -r requirements.txt
```

## Настройка `.env`

```env
API_ID=123456
API_HASH=...
BOT_TOKEN=...
SESSION_STRING=...
CONTROL_CHAT_ID=-100...
```

`CONTROL_CHAT_ID` — ID управляющего чата (например, «Избранное”). Узнать ID: перешлите сообщение боту `@userinfobot` или `@getidsbot`.

## Запуск

```bash
python main.py
```

При старте `main.py` проверяет переменные окружения и валидирует `targets.yaml` — конфиг с ошибками будет отклонён сразу, а не посреди прогона.

## Использование управляющего бота

| Команда | Описание |
|---|---|
| `/start`, `/help` | Список команд |
| `/bot-1` | Запуск сценария `bot-1` из `targets.yaml` |
| `/status` | Статус текущих прогонов |
| `/count` | Сколько ссылок в базе |
| `/links [N]` | Показать последние N ссылок (по умолчанию 5) |
| `/export` | Выгрузить базу в CSV |
| `/list` | Доступные сценарии |

Во время прогона бот присылает live-прогресс вида:

```text
[2/7] Waiting for button "Получить"
Found: 5 | Saved: 3
```

Неизвестные команды ничего не запускают — бот отвечает подсказкой со списком доступных команд.

---

## `targets.yaml`

```yaml
defaults:
  timeout: 20          # таймаут click, сек
  extract_window: 60   # окно extract, сек

bots:
  bot-1:
    username: "@FreeVpnBot"
    scenario:
      - send: "получить vpn"
      - click:
          text: "Получить"        # подстрока, регистр не важен
          timeout: 25             # опционально, переопределяет defaults
      - extract: true

  bot-2:
    username: "@AnotherBot"
    scenario:
      - send: "/start"
      - click: { text: "Start" }
      - extract: true

  # Сценарий с подпиской на канал/инвайт
  bot-3:
    username: "@InviteBot"
    scenario:
      - subscribe:
          chat: "@vpn_news"        # или invite: "https://t.me/+hash"
          timeout: 15
      - send: "start"
      - click: { text: "Start" }
      - extract: true
```

### Действия сценария

| Действие | Описание |
|---|---|
| `send` | Отправить текст в чат целевого бота (userbot-клиент). |
| `click` | Ждать inline-кнопку с подстрокой `text` (регистр не важен) до `timeout` (по умолчанию 20 c), нажать только кнопку целевого бота. Таймаут → ошибка с понятной причиной. |
| `extract` | Сканировать **все** сообщения от целевого бота в чате, извлекать VLESS-ссылки и subscription URL и сохранять новые найденные ссылки. |
| `subscribe` | Вступить в `chat` (`@channel`) или по `invite` (`https://t.me/+hash`) от имени userbot. Уже подписан → пропуск с пометкой. Проверка членства после входа. |

После `extract` в `Found:` попадают уникальные ссылки прогона, в `Saved:` — реально новые для `links.db`.

Subscription URL распознаётся, только если в path есть отдельный сегмент `sub`. Домен не ограничен: подходят ссылки вида `/sub`, `/sub/...`, `/api/sub/...` и `/path/sub?...`. Обычные HTTP(S)-ссылки, а также пути `/submit` и `/subscribe` игнорируются. Query string сохраняется полностью; содержимое subscription URL не скачивается. VLESS и subscription URL хранятся в одной таблице `links`, где дедупликация обеспечивается ограничением `UNIQUE`.

### Валидация конфига

Ошибки конфигурации понятны и указывают шаг:

```text
bot-1: step 3: action 'click' requires field 'text'
bot-2: action 'subscribe' requires 'chat' or 'invite'
bot-5: unknown action 'clik' in step 2 (valid: send, click, extract, subscribe)
```

Конфиг проверяется при старте и непосредственно перед запуском сценария.

### Параллелизм

- Один и тот же `bot_id` **не запускается дважды** параллельно: повторная команда мгновенно отвечает `Scenario bot-1 is already running`.
- Разные `bot_id` бегут **параллельно**, без перекрёстных обработчиков.

---

## Локальные проверки

Тесты парсера, `extract` и совместимости с SQLite находятся в репозитории:

```bash
venv311\Scripts\python.exe -m unittest discover -s tests -v  # 16 тестов
```

Они проверяют VLESS, subscription URL любого домена, точный path-сегмент `sub`, query string, Markdown, пунктуацию, дедупликацию, несколько сообщений сценария и существующее ограничение `UNIQUE` в SQLite.

Расширенный офлайн-набор можно запускать из `%TEMP%\opencode\vpnfree_tests`:

```bash
venv311\Scripts\python.exe  <temp>\vpnfree_tests\test_core.py         # 32 теста
venv311\Scripts\python.exe  <temp>\vpnfree_tests\test_control_bot.py  # 15 тестов
venv311\Scripts\python.exe  <temp>\vpnfree_tests\test_e2e.py          # e2e /bot-1
```

Также проверено:

- `git check-ignore .env links.db x.session` → игнорируются;
- в `*.py` нет `API_HASH` / `BOT_TOKEN` / `SESSION_STRING`;
- `storage.py` не изменён, существующая таблица `links` принимает оба типа ссылок;
- `py_compile` по изменённым файлам проекта чистый;
- реальный `targets.yaml` проходит валидацию.

### Что нельзя проверить без Telegram

1. Реальный MTProto-логин userbot и вход по `SESSION_STRING`.
2. Живое нажатие кнопки в конкретном боте (формат кнопок, callback-ответы).
3. Фактическую доставку сообщений бота в ваш чат.
4. Вступление в канал/инвайт и обработку `FloodWait` на стороне Telegram.
5. Что целевой бот отвечает на `send` в вашем аккаунте.

Рекомендуется начать с **read-only прогона**: `/bot-1` на боте, который шлёт ссылку без подписки, и убедиться, что `Found:`/`Saved:` сходятся, а `links.db` пополняется.

---

## Ручной запуск сценария (без бота)

```python
import asyncio
from orchestrator import load_config, run_scenario
from interaction import ScenarioRunner
from main import make_client
from storage import init_db, save_link

async def go():
    cfg = load_config("targets.yaml")
    init_db()
    client = make_client()
    async with client:
        res = await run_scenario(
            ScenarioRunner(client, cfg["bots"]["bot-1"], cfg.get("defaults") or {}),
            "bot-1", on_progress=lambda s: print("  ", s),
        )
    for link in res.links:
        save_link(link)

asyncio.run(go())
```

---

## Известные замечания

1. **`venv311/` закоммичен в Git** (~3595 файлов, бинарники и `.exe`). В `.gitignore` его нет. Рекомендуется очистить индекс (файлы на диске останутся):
   ```bash
   git rm -r --cached venv311
   git add .gitignore
   git commit -m "chore: untrack venv"
   ```
2. **`tools/convert_tdata.py`** печатает `api_hash` в консоль (`print("api_hash:", ...)`). Перед публикацией репозитория уберите этот вывод или удалите файл.
3. Click после нажатия ждёт пост-клик ответа best-effort: ответ бота **всё равно буферизуется** и будет пойман `extract`-ом, поэтому отсутствие видимой реакции не валит шаг; таймаут валит только ожидание кнопки.

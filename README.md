---
title: "Кофейный бариста"
description: "Тематический чат с Gemini, общим ключом доступа и постоянной историей."
references:
  ".env.example": "f361f16aceb858a95c1a738077a3ea2861cc1bc713b39e56dfed88e8f387d309"
  "Dockerfile": "4edbe16d83a4310ee20c86615801bd0213ccc1886f444eb4790e67aefc82a114"
  "Makefile": "b933dae1091c89574efc9b985112e528b5ca0b772ac6c16ff40edd50be4c080c"
  "compose.override.yaml": "914bb24325085f49a3171fb4879ab4399858dcf4e0cd15898fce17ea73d6290f"
  "compose.yaml": "ffe0e864ca2ce79d920eab4e90b8aec50b459449859ae920887652d235ffce27"
  "config/app.yaml": "5b859bfc63331410d12f42fbbab51d6f2c0bfb4a9f5586a324068001bef5d61d"
  "pyproject.toml": "91df518c61cf518b581ab739795a4c79c51d7a8d15b904f41667482f6a843a51"
  "src/themed_chat/adapters/database.py": "aa7087860a313178fca3d61abee2fe9eeffeb0a5b2a60a4bc6bd74bdb8f05d1a"
  "src/themed_chat/api/auth_middleware.py": "a4d8602f02fe940281ce692972dc00ebda04af2f34ba2404e3cdff7f9ecaabe4"
  "src/themed_chat/api/chat_routes.py": "9136a71f7e58d676bf4efb2912b096420d0f60403033b13088d754c5c818321d"
  "src/themed_chat/app.py": "a18889943c62cebd02ec522cdce98ed7a18d774fe85628e4f63f3edffc8caef8"
  "tests/unit/test_docs.py": "192024e6e0c94f5161ff97244faf3fabb1d18fe481909a6bfe26e05a7506bc63"
---

# Кофейный бариста

Одностраничный помощник по домашнему завариванию кофе. История одна для всех участников с ключом; не отправляйте личные данные. Gemini получает системную инструкцию и текущий вопрос, но не всю историю.

## Быстрый запуск

Нужны Docker с Compose v2 и [ключ Gemini API](https://aistudio.google.com/app/apikey). Запускайте команды из корня клонированного проекта по очереди. На шаге с редактором заполните `.env`, прежде чем запускать контейнер.

```sh
(umask 077; cp .env.example .env)
${EDITOR:-vi} .env
docker compose up --build -d --wait
```

Заполните `APP_ACCESS_KEY` (8–255 символов: `A–Z`, `a–z`, цифры, `-`, `_`), `APP_SESSION_SECRET` (не короче 32 символов), `GEMINI_API_KEY` и `POSTGRES_PASSWORD`. Для ключа доступа, секрета сессии и локального пароля PostgreSQL выполните `openssl rand -hex 32` три раза: значения должны быть независимыми, а пароль БД сразу подставляется в URL и должен быть в hex. В браузер вводится **только `APP_ACCESS_KEY`**.

Откройте **http://127.0.0.1:8000**. Не используйте `localhost` вместо `127.0.0.1`: API сверяет точный origin. Если порт занят, запустите, например, `CHAT_PORT=8080 docker compose up --build -d --wait` и откройте `http://127.0.0.1:8080`. При явно заданном `APP_AUTH__PUBLIC_ORIGIN` укажите тот же адрес и порт. `docker compose down` останавливает сервисы, не удаляя историю. Не добавляйте `-v`, если нужно сохранить данные.

## Конфигурация

| Где | Что задаётся |
|---|---|
| [config/app.yaml](config/app.yaml) | Заголовок, поставщик, модель, системный промпт, таймаут, лимит ответа и время жизни сессии. После изменения YAML пересоберите образ. |
| [.env.example](.env.example) → локальный `.env` | Ключ доступа, секрет сессии, ключ Gemini и параметры PostgreSQL. Не коммитьте `.env`. Настройки приложения можно переопределить переменными вида `APP_СЕКЦИЯ__ПОЛЕ`, например `APP_LLM__MODEL`. |
| [compose.yaml](compose.yaml) и [compose.override.yaml](compose.override.yaml) | Базовый файл запускает чат; автоматически подключаемый override добавляет локальный PostgreSQL и формирует `DATABASE_URL` из `POSTGRES_PASSWORD`. |

### Хранилище

При обычном `docker compose up` PostgreSQL 17 запускается вместе с чатом. Порт БД не публикуется на хосте; данные хранятся в именованном томе `postgres-data`. Не меняйте `POSTGRES_PASSWORD` для существующего тома без отдельной смены пароля в самой БД: образ PostgreSQL использует эту переменную при инициализации пустого тома.

**Облачная PostgreSQL.** В `.env` не нужен `POSTGRES_PASSWORD`; задайте `DATABASE_URL`, например:

```dotenv
DATABASE_URL=postgresql+asyncpg://user:password@db.example.com:5432/themed_chat?ssl=verify-full
PGSSLROOTCERT=/etc/ssl/certs/ca-certificates.crt
```

Запустите только базовый Compose-файл, без локальной БД:

```sh
docker compose -f compose.yaml up --build -d --wait
```

`verify-full` проверяет сертификат и имя хоста. Для CA провайдера примонтируйте его в контейнер только для чтения и укажите путь в `PGSSLROOTCERT`. Спецсимволы в имени пользователя и пароле кодируйте для URL (например, `$` → `%24`). База должна существовать и принимать подключения от приложения; роль должна иметь право применять миграции Alembic. Автоматический запуск миграций рассчитан на один процесс приложения. Если переходите с уже запущенного локального стека, сначала остановите его командой `docker compose down` с прежним окружением, сохранив том.

Старая история из SQLite не переносится автоматически: существующие файлы и том не удаляются.

Если модель недоступна для вашего ключа, замените `llm.model` на доступную в [каталоге Gemini](https://aistudio.google.com/docs/models). Сервис не подставляет фальшивый ответ при ошибке провайдера.

## Устройство проекта

- [app.py](src/themed_chat/app.py) собирает зависимости и управляет жизненным циклом SQLAlchemy и асинхронного SDK. `create_app()` позволяет подставить текстовый генератор и согласованную пару репозиториев.
- [api/](src/themed_chat/api/) отвечает за маршруты, проверку ключа и сессии. Браузер отправляет `X-Access-Key` только при входе и затем использует подписанную HttpOnly cookie. Сессия даёт гостевой ID, а не учётную запись; клиент не выбирает автора запроса.
- [chat/](src/themed_chat/chat/) содержит сценарий и порты. Вызов модели выполняется **вне** транзакции; только готовая пара реплик сохраняется вместе.
- [adapters/](src/themed_chat/adapters/) реализует доступ к БД и Gemini; [migrations/](src/themed_chat/migrations/) содержит версии схемы. [web/](src/themed_chat/web/) — HTML, CSS и JavaScript без фреймворка.

| Запрос | Результат |
|---|---|
| `POST /api/session` | Проверяет `X-Access-Key` и выдаёт cookie (`204`). |
| `GET /api/session` | Проверяет, что сессия действует (`204`). |
| `GET /api/messages` | Заголовок и общая история; дата и время в UTC. |
| `POST /api/messages` с `{"text":"Как заварить фильтр?"}` | Сохраняет и возвращает пару реплик (`201`). Предел — 500 Unicode-символов, пробельные сообщения не принимаются. |

Закрытые маршруты требуют сессию. Для запросов, меняющих состояние, сервер требует точный `Origin`. После истечения cookie повторный вход создаёт нового гостя; история остаётся общей.

## Проверки

Для интеграционных тестов и браузерного E2E нужен **отдельный тестовый сервер PostgreSQL** и роль с `CREATEDB`. Например, запустите временный контейнер:

```sh
docker run --rm -d --name themed-chat-test-db -e POSTGRES_PASSWORD=test-only -p 127.0.0.1:55432:5432 postgres:17-alpine
docker exec themed-chat-test-db pg_isready -h 127.0.0.1 -U postgres
export TEST_POSTGRES_URL='postgresql+asyncpg://postgres:test-only@127.0.0.1:55432/postgres?ssl=disable'
make check
uv run --locked --group browser playwright install chromium
make e2e
docker stop themed-chat-test-db
```

Если `pg_isready` ещё не подтверждает готовность, повторите проверку перед запуском тестов. Не используйте сервер с рабочими данными. Каждый тест с БД создаёт и удаляет только свою временную базу. `make check` проверяет lock-файл, Ruff, mypy, документацию, unit- и HTTP/API-тесты. E2E запускает настоящий HTTP-сервер, Chromium и PostgreSQL. Ключ Gemini для тестов не нужен: адаптер проверяется с реальным SDK и подменой HTTP-транспорта.

## Что можно доработать

- Пагинация истории, лимиты входа и генерации для публичного деплоя, мониторинг квот.
- Серверная идемпотентность запроса. Сейчас при потере ответа интерфейс просит проверить историю, прежде чем разрешить повтор; это не гарантия однократной записи.
- Отдельный запуск миграций для нескольких реплик, резервное копирование и перенос данных между БД. Вместо общего ключа — индивидуальные учётные записи, если требуется личная история.

Подробнее: [план реализации](docs/implementation-plan.md) и [локальный реестр работ](docs/issues/README.md).

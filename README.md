---
title: "Кофейный бариста"
description: "Тематический чат с настраиваемым LLM-провайдером, общим ключом доступа и постоянной историей."
references:
  "src/themed_chat/adapters/openai_compatible.py": "0ff223bac1707ea7c4a14a104bd5589ef592a470d8a9f85e781cb9bd8c2e4af5"
  "src/themed_chat/settings.py": "95089aaeab21420a9de27d8968beffceba727ad7144899a1d82370b8fc781a03"
  ".dockerignore": "a90d30c8d1a25694dee6f5e1bd4e10f0a87b79a17bd8e6628b1e611197a2f2b0"
  "deploy/helm/themed-chat/Chart.yaml": "40212058339ec05ef383cef5c89b6f5cdcb036ebe1b799f5054a312a216e680f"
  "deploy/helm/themed-chat/values.yaml": "cde4c9b990ebbf11d6e3446c988f65c3050a1304edcdab8aef3b3ccd9113e54d"
  "deploy/helm/themed-chat/templates/_helpers.tpl": "e47a8adb077e305c76a0a737bef092b8a799e4a7d72b9784e57dc537e74ba216"
  "deploy/helm/themed-chat/templates/deployment.yaml": "912a1630157a81487b6d20d56ca463d0f554e5e68d1db68218c914a87f31052a"
  "deploy/helm/themed-chat/templates/service.yaml": "c02ea24783b035be44fb5dd702b9572bad26fadb5839dd7f36d7a3c56b863c62"
  ".env.example": "e33ef8a7012fcfea824ebdeb10ae3eb23d8d3f7b467b4bb761a327cbf36999d2"
  "Dockerfile": "168d3fd0efa3b783d84443f2093fb9fd2867caba128a85f7f56204b11b13cb04"
  "Makefile": "b933dae1091c89574efc9b985112e528b5ca0b772ac6c16ff40edd50be4c080c"
  "compose.local.yaml": "58246fa88804c44aff643e1c44e35303daa9ae6fee4145c7e4c8322689952339"
  "config/app.yaml": "5b859bfc63331410d12f42fbbab51d6f2c0bfb4a9f5586a324068001bef5d61d"
  "pyproject.toml": "248c488092a49812571a7c344aef60965be2a3b966a928ea995ebe752c9ddd00"
  "src/themed_chat/adapters/database.py": "8e91f00852ce622d6740899cdfef376e65bfa6136c10acc95b3033f93ff2a3cf"
  "src/themed_chat/api/auth_middleware.py": "a4d8602f02fe940281ce692972dc00ebda04af2f34ba2404e3cdff7f9ecaabe4"
  "src/themed_chat/api/chat_routes.py": "9136a71f7e58d676bf4efb2912b096420d0f60403033b13088d754c5c818321d"
  "src/themed_chat/app.py": "f5252ae39d9745cfaebf4caa727f06e8cf9ef1deebce3d4ff97450d2f4bba223"
  "tests/unit/test_docs.py": "5913b2ecaa5d26a532fa3422533674f6a3b320f13c4f9b816c495f795a1b5dbe"
---

# Кофейный бариста

Одностраничный помощник по домашнему завариванию кофе. История одна для всех участников с ключом; не отправляйте личные данные. Модель получает системную инструкцию и текущий вопрос, но не всю историю.

## Быстрый запуск

Нужны Docker с Compose v2 и ключ выбранного провайдера ([Gemini по умолчанию](https://aistudio.google.com/app/apikey)). Запускайте команды из корня клонированного проекта по очереди. На шаге с редактором заполните `.env`, прежде чем запускать контейнер.

```sh
(umask 077; cp .env.example .env)
${EDITOR:-vi} .env
docker compose -f compose.local.yaml up --build -d --wait
```

Заполните `APP_ACCESS_KEY` (8–255 символов: `A–Z`, `a–z`, цифры, `-`, `_`), `APP_SESSION_SECRET` (не короче 32 символов), `POSTGRES_PASSWORD` и ключ выбранного провайдера (`GEMINI_API_KEY` по умолчанию). Для ключа доступа, секрета сессии и локального пароля PostgreSQL выполните `openssl rand -hex 32` три раза: значения должны быть независимыми. Используйте hex для пароля, чтобы избежать интерполяции спецсимволов в Compose. В браузер вводится **только `APP_ACCESS_KEY`**.

Откройте **http://127.0.0.1:8000**. Не используйте `localhost` вместо `127.0.0.1`: API сверяет точный origin. Если порт занят, запустите, например, `CHAT_PORT=8080 docker compose -f compose.local.yaml up --build -d --wait` и откройте `http://127.0.0.1:8080`. При явно заданном `APP_AUTH__PUBLIC_ORIGIN` укажите тот же адрес и порт. `docker compose -f compose.local.yaml down` останавливает сервисы, не удаляя историю. Не добавляйте `-v`, если нужно сохранить данные.

## Конфигурация

| Где | Что задаётся |
|---|---|
| [config/app.yaml](config/app.yaml) | Заголовок, поставщик, модель, системный промпт, таймаут, лимит ответа и время жизни сессии. После изменения YAML пересоберите образ. |
| [.env.example](.env.example) → локальный `.env` | Ключ доступа, секрет сессии, ключ провайдера и параметры PostgreSQL. Не коммитьте `.env`. Настройки приложения можно переопределить переменными вида `APP_СЕКЦИЯ__ПОЛЕ`, например `APP_LLM__MODEL`. |
| [compose.local.yaml](compose.local.yaml) | Запускает чат и PostgreSQL 17 для локальной разработки; порт БД не публикуется. |

### Хранилище

Локальная история хранится в именованном томе `postgres-data`. При обновлении со старого Compose сохраните прежнее имя проекта: смена имени приведёт к созданию другого тома. Не меняйте `POSTGRES_PASSWORD` для существующего тома без отдельной смены пароля в самой БД: образ использует переменную при инициализации пустого тома.

**Обновление с SQLite.** Прежде чем обновлять, остановите старый стек командой `docker compose down` без `-v`. Сделайте резервную копию файла `/data/chat.sqlite3` из прежнего именованного тома `<имя-проекта>_chat-data` (или `data/chat.sqlite3` при старом запуске без Docker). Не очищайте этот том: PostgreSQL начнёт с пустой истории, автоматического импорта нет. Для отката запустите старый коммит `a43bf10` с прежним `.env` и тем же именем Compose-проекта, чтобы он подключил прежний том.

Если модель недоступна для вашего ключа, замените `llm.model` на доступную в [каталоге Gemini](https://aistudio.google.com/docs/models). Сервис не подставляет фальшивый ответ при ошибке провайдера.

### Qwen и другие OpenAI-совместимые модели

Для Compose добавьте в `.env`:

```dotenv
APP_LLM__PROVIDER=openai_compatible
APP_LLM__BASE_URL=https://YOUR-WORKSPACE.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1
APP_LLM__MODEL=qwen-plus
OPENAI_COMPATIBLE_API_KEY=your-model-studio-api-key
```

Укажите адрес своего региона и ключ оттуда же ([Alibaba Cloud Model Studio](https://docs.modelstudio.console.alibabacloud.com/en/model-studio/qwen-api-via-openai-chat-completions)). Указывайте базовый URL без `/chat/completions`; для облака используйте HTTPS. Сервер должен поддерживать текстовый Chat Completions с `system`, `user` и `max_tokens`. `GEMINI_API_KEY` в этом режиме не нужен. Примените настройки командой `docker compose -f compose.local.yaml up -d --force-recreate --no-deps chat` (если образ уже собран с новым адаптером). Также можно задать `llm.provider`, `llm.base_url` и `llm.model` в [app.yaml](config/app.yaml) и пересобрать образ.

Для Helm укажите `llm.provider=openai_compatible`, `llm.baseUrl` и `llm.model` в [values](deploy/helm/themed-chat/values.yaml), а `OPENAI_COMPATIBLE_API_KEY` — в `existingSecret`. Не кладите ключ в values. Если сервер модели запущен на хосте Docker Desktop, используйте доступный контейнеру адрес (например, `host.docker.internal`), а не `localhost`.

## Развёртывание в Kubernetes

[Helm-чарт](deploy/helm/themed-chat/Chart.yaml) устанавливает только приложение: один `Deployment` и внутренний `ClusterIP` на порту 8000. PostgreSQL и Ingress чарт не создаёт. Для запуска нужны кластер Kubernetes, `kubectl`, Helm, готовая PostgreSQL и доступный кластеру образ из [Dockerfile](Dockerfile). Публикуемого образа по умолчанию нет: соберите образ, например `docker build -t YOUR_REGISTRY/themed-chat:0.1.0 .`, и загрузите его в свой реестр. Для закрытого реестра можно указать `imagePullSecrets` в [values.yaml](deploy/helm/themed-chat/values.yaml).

### Установка

В namespace `themed-chat` заранее создайте Secret `themed-chat-runtime` с настройками: `APP_ACCESS_KEY`, `APP_SESSION_SECRET`, `DATABASE_URL` и ключ выбранного провайдера (`GEMINI_API_KEY` или `OPENAI_COMPATIBLE_API_KEY`). Можно подготовить отдельный файл `$HOME/.config/themed-chat/runtime.env` вне рабочей копии с этими ключами в формате `KEY=value` и правами `0600`; не кладите его в репозиторий, values или образ. Не используйте локальный Compose `.env` в качестве этого файла. Сгенерируйте независимые ключ доступа и секрет сессии, как описано в разделе «Быстрый запуск».

```sh
kubectl create namespace themed-chat
kubectl -n themed-chat create secret generic themed-chat-runtime --from-env-file="$HOME/.config/themed-chat/runtime.env"
helm upgrade --install coffee ./deploy/helm/themed-chat \
  --namespace themed-chat --wait --timeout 5m \
  --set-string image.repository=YOUR_REGISTRY/themed-chat \
  --set-string image.tag=0.1.0 --set-string existingSecret=themed-chat-runtime
kubectl -n themed-chat port-forward svc/coffee-themed-chat 8000:8000
```

Имя Helm-релиза должно начинаться со строчной латинской буквы; дальше допустимы строчные латинские буквы, цифры и дефисы. Откройте `http://127.0.0.1:8000`. При доступе через внешний шлюз настройте маршрутизацию на этот Service и задайте `publicOrigin` равным точному HTTPS-адресу без пути и завершающего `/`, например `https://chat.example.com`. Для `port-forward` на другом порту поменяйте и `publicOrigin`, и адрес в браузере.

### Подключение к PostgreSQL

Формат `DATABASE_URL`: `postgresql+asyncpg://user:password@db.example.com:5432/themed_chat?ssl=verify-full`. Целевая база должна существовать, приниматься с сети Pod и позволять роли применить миграции Alembic. Кодируйте спецсимволы в имени и пароле для URL. По умолчанию `PGSSLROOTCERT` указывает на системный набор сертификатов образа. Если БД использует частный CA, создайте в том же namespace Secret с ключом `ca.crt` и укажите его имя в `postgresCASecret`; чарт примонтирует сертификат только для чтения.

Миграции выполняются при старте под транзакционной advisory-блокировкой PostgreSQL: если два Pod стартуют одновременно, второй ждёт завершения первого. Чарт использует одну реплику и стратегию `Recreate`; при обновлении возможен короткий простой. При изменении значений в существующем Secret перезапустите Pod, например `kubectl -n themed-chat rollout restart deployment/coffee-themed-chat`. Удаление Helm-релиза не удаляет Secret и внешнюю БД.

## Устройство проекта

- [app.py](src/themed_chat/app.py) собирает зависимости и управляет жизненным циклом SQLAlchemy и асинхронного SDK. `create_app()` позволяет подставить текстовый генератор и согласованную пару репозиториев.
- [api/](src/themed_chat/api/) отвечает за маршруты, проверку ключа и сессии. Браузер отправляет `X-Access-Key` только при входе и затем использует подписанную HttpOnly cookie. Сессия даёт гостевой ID, а не учётную запись; клиент не выбирает автора запроса.
- [chat/](src/themed_chat/chat/) содержит сценарий и порты. Вызов модели выполняется **вне** транзакции; только готовая пара реплик сохраняется вместе.
- [adapters/](src/themed_chat/adapters/) реализует доступ к БД и LLM; [migrations/](src/themed_chat/migrations/) содержит версии схемы. [web/](src/themed_chat/web/) — HTML, CSS и JavaScript без фреймворка.

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

Если `pg_isready` ещё не подтверждает готовность, повторите проверку перед запуском тестов. Не используйте сервер с рабочими данными. Каждый тест с БД создаёт и удаляет только свою временную базу. `make check` проверяет lock-файл, Ruff, mypy, документацию, unit- и HTTP/API-тесты. E2E запускает настоящий HTTP-сервер, Chromium и PostgreSQL. Ключ провайдера для тестов не нужен: адаптеры проверяются с реальным SDK и подменой HTTP-транспорта.

## Что можно доработать

- Пагинация истории, лимиты входа и генерации для публичного деплоя, мониторинг квот.
- Серверная идемпотентность запроса. Сейчас при потере ответа интерфейс просит проверить историю, прежде чем разрешить повтор; это не гарантия однократной записи.
- Отдельный запуск миграций для нескольких реплик, резервное копирование и перенос данных между БД. Вместо общего ключа — индивидуальные учётные записи, если требуется личная история.

---
title: "Кофейный бариста"
description: "Тематический чат с настраиваемым LLM-провайдером, общим ключом доступа и постоянной историей."
references:
  "src/themed_chat/adapters/openai_compatible.py": "35d6a3a9f12e9dc8e9e610c401a46132b86beae78724f0ebd7e9bd7d19cb0f54"
  "src/themed_chat/settings.py": "b8f77dfb61619df96d535f3df4972ea3218b8807453e597d4dd1b6d8d878ee2c"
  ".dockerignore": "a90d30c8d1a25694dee6f5e1bd4e10f0a87b79a17bd8e6628b1e611197a2f2b0"
  "deploy/helm/themed-chat/Chart.yaml": "40212058339ec05ef383cef5c89b6f5cdcb036ebe1b799f5054a312a216e680f"
  "deploy/helm/themed-chat/values.yaml": "8604d80dbd50d0c62eb20c0db15bd85faa7f81d33432b7a50de938d79fe857d4"
  "deploy/helm/themed-chat/templates/_helpers.tpl": "e47a8adb077e305c76a0a737bef092b8a799e4a7d72b9784e57dc537e74ba216"
  "deploy/helm/themed-chat/templates/deployment.yaml": "7d394517470d2bcfd104c02cb71eddea20203e20390235fb6c20ca846663f27f"
  "deploy/helm/themed-chat/templates/service.yaml": "c02ea24783b035be44fb5dd702b9572bad26fadb5839dd7f36d7a3c56b863c62"
  ".env.example": "c42ed86a70757bae0486fc0c583b2605444b3076b064edd5120c22c5340cd934"
  "Dockerfile": "168d3fd0efa3b783d84443f2093fb9fd2867caba128a85f7f56204b11b13cb04"
  "Makefile": "b933dae1091c89574efc9b985112e528b5ca0b772ac6c16ff40edd50be4c080c"
  "compose.local.yaml": "58246fa88804c44aff643e1c44e35303daa9ae6fee4145c7e4c8322689952339"
  "config/app.yaml": "da90cbbe1b172a6b6ca506ae97215c07c8667546698c5df2ccc86b979ae78e69"
  "pyproject.toml": "117799f27f5f4de319f9b87b32ba4d7245118ccaaf5c00a86637b639f7dacb4a"
  "src/themed_chat/adapters/database.py": "8e91f00852ce622d6740899cdfef376e65bfa6136c10acc95b3033f93ff2a3cf"
  "src/themed_chat/api/auth_middleware.py": "a4d8602f02fe940281ce692972dc00ebda04af2f34ba2404e3cdff7f9ecaabe4"
  "src/themed_chat/api/chat_routes.py": "9136a71f7e58d676bf4efb2912b096420d0f60403033b13088d754c5c818321d"
  "src/themed_chat/app.py": "a0a4baae75d9ac4060108793f89339b6ace2c5bf5e23da45bce52612607faa8a"
  "tests/unit/test_docs.py": "5913b2ecaa5d26a532fa3422533674f6a3b320f13c4f9b816c495f795a1b5dbe"
---

# Кофейный бариста

Чат-помощник по домашнему завариванию кофе. Вход по общему ключу, история общая для всех — не пишите личные данные. Модель видит только системный промпт и текущий вопрос.

## Быстрый запуск

Нужны Docker Compose v2 и ключ выбранного API ([Google AI Studio](https://aistudio.google.com/app/apikey) для модели по умолчанию). Запускайте команды из корня проекта по очереди: перед запуском контейнеров заполните `.env`.

```sh
(umask 077; cp .env.example .env)
${EDITOR:-vi} .env
docker compose -f compose.local.yaml up --build -d --wait
```

В `.env` заполните `LLM_API_KEY` для выбранного адреса API, а `APP_ACCESS_KEY`, `APP_SESSION_SECRET` и `POSTGRES_PASSWORD` — тремя разными значениями `openssl rand -hex 32`. В браузере вводится только `APP_ACCESS_KEY`.

Откройте **http://127.0.0.1:8000** (не `localhost`: API сверяет точный origin). Другой порт: `CHAT_PORT=8080 docker compose -f compose.local.yaml up --build -d --wait` (если задан `APP_AUTH__PUBLIC_ORIGIN`, порт в нём должен совпадать). Остановка без потери истории — `docker compose -f compose.local.yaml down` (без `-v`).

## Конфигурация

- [config/app.yaml](config/app.yaml) — настройки по умолчанию. В секции `llm` задаются `base_url` и `model`. По умолчанию указан совместимый API Google Gemini. После правки YAML пересоберите образ.
- [.env.example](.env.example) — шаблон для `.env` в корне проекта. В Compose переменные `APP_LLM__MODEL` и `APP_LLM__BASE_URL` переопределяют YAML без пересборки уже обновлённого образа. Ключ храните в `.env`, не коммитьте его.
- [compose.local.yaml](compose.local.yaml) запускает чат и PostgreSQL 17. Порт БД не публикуется, история хранится на томе `postgres-data`. При обновлении сохраните прежнее имя Compose-проекта. Правка `POSTGRES_PASSWORD` в `.env` не меняет пароль уже созданной БД. Не указывайте `DATABASE_URL` при локальном запуске.

**Переход с SQLite.** В старой версии остановите стек без `-v` и сохраните `/data/chat.sqlite3` из тома `<проект>_chat-data` (или локальный файл БД, если запускали без Docker). Данные автоматически не переносятся. Для отката используйте коммит `a43bf10`, прежний `.env` и то же имя Compose-проекта.

### Переключение модели

Выберите базовый URL и ID модели, а `LLM_API_KEY` возьмите у сервиса для этого URL. В локальном Compose эти три значения задаются в `.env`. Например, для Frontier AI:

```dotenv
APP_LLM__BASE_URL=https://klinskoe17.frontierai.ru/v1
APP_LLM__MODEL=glm-5.3-flash-cb
LLM_API_KEY=your-frontier-api-key
```

Для [Gemini](https://aistudio.google.com/docs/openai) укажите `https://generativelanguage.googleapis.com/v1beta/openai/`, доступный ID (например, `gemini-3.8-flash`) и ключ Google в `LLM_API_KEY`. Для [Qwen](https://docs.modelstudio.console.alibabacloud.com/en/model-studio/qwen-api-via-openai-chat-completions) — базовый URL своего Model Studio workspace, доступный ID (например, `qwen-plus`) и ключ того же региона.

Не дописывайте `/chat/completions`: клиент сам добавляет путь. API должен принимать Bearer-ключ, `messages` с ролями `system` и `user`, `max_tokens` и возвращать строку в `choices[0].message.content`. С облачным ключом используйте HTTPS и меняйте ключ вместе с URL: он отправляется на настроенный адрес. Для сервера на хосте Docker Desktop используйте доступный контейнеру адрес, например `host.docker.internal`, а не `localhost`.

После смены настроек выполните `docker compose -f compose.local.yaml up -d --wait`. При первом запуске или обновлении кода добавьте `--build`.

**Переход со старой версии:** в `.env` переименуйте ключ действующего сервиса в `LLM_API_KEY`, в Kubernetes Secret добавьте его под новым именем. Уберите `APP_LLM__PROVIDER` / `llm.provider`; для Google теперь используется совместимый `base_url`. Для Compose пересоберите образ. Для Helm опубликуйте образ, который читает `LLM_API_KEY`, под новым уникальным тегом и укажите этот тег при обновлении чарта. Старый ключ в Secret можно сохранить до окончания проверки, чтобы не сломать откат.

## Развёртывание в Kubernetes

[Helm-чарт](deploy/helm/themed-chat/Chart.yaml) ставит только приложение: `Deployment` с одной репликой (`Recreate`) и `ClusterIP` на порту 8000. PostgreSQL, Ingress и готовый образ — ваши: соберите [Dockerfile](Dockerfile) и загрузите в свой реестр (для закрытого — `imagePullSecrets` в [values.yaml](deploy/helm/themed-chat/values.yaml)).

Для продового PostgreSQL укажите полную строку подключения в `DATABASE_URL` существующего Secret (`existingSecret`). Если создаёте Secret из файла, подготовьте `$HOME/.config/themed-chat/runtime.env` с правами `0600` вне репозитория:

```dotenv
APP_ACCESS_KEY=<ключ-доступа-к-чату>
APP_SESSION_SECRET=<секрет-подписи-сессии>
DATABASE_URL=postgresql+asyncpg://user:password@host:5432/themed_chat?ssl=verify-full
LLM_API_KEY=<ключ-модели>
```

URL API модели и её ID задаются вместе в `llm.baseUrl` и `llm.model` в [values.yaml](deploy/helm/themed-chat/values.yaml) либо через `--set-string`. Если оба поля пусты, используются настройки из [config/app.yaml](config/app.yaml).

```sh
kubectl create namespace themed-chat
kubectl -n themed-chat create secret generic themed-chat-runtime --from-env-file="$HOME/.config/themed-chat/runtime.env"
helm upgrade --install coffee ./deploy/helm/themed-chat \
  --namespace themed-chat --wait --timeout 5m \
  --set-string image.repository=YOUR_REGISTRY/themed-chat \
  --set-string image.tag=0.1.0 --set-string existingSecret=themed-chat-runtime
kubectl -n themed-chat port-forward svc/coffee-themed-chat 8000:8000
```

- Имя релиза: строчные латинские буквы, цифры и `-`, начинается с буквы.
- За внешним шлюзом задайте `publicOrigin` — точный HTTPS-адрес без пути и `/` на конце (`https://chat.example.com`). Для `port-forward` на другой порт тоже поменяйте `publicOrigin`.
- База PostgreSQL должна существовать, роль — уметь применять миграции Alembic. Из параметров `DATABASE_URL` допустим только `ssl`, спецсимволы в логине и пароле кодируйте (`$` → `%24`).
- Частный CA: Secret с ключом `ca.crt`, его имя — в `postgresCASecret`.
- Миграции идут при старте под advisory-блокировкой, параллельные Pod ждут друг друга.
- После правки Secret: `kubectl -n themed-chat rollout restart deployment/coffee-themed-chat`. `helm uninstall` не удаляет Secret и БД.

### Frontier AI в проде

Передайте URL Frontier AI и модель GLM при обновлении релиза. Адрес самого чата (`publicOrigin`) не меняется.

1. Подготовьте Secret с ключом Frontier AI под именем `LLM_API_KEY` и теми же настройками приложения и БД. При переходе с другого сервиса используйте новый Secret, чтобы старый релиз мог откатиться со своим ключом. Не передавайте токен в Helm values.
2. Обновите существующий релиз. Укажите имя релиза, namespace, контекст прод-кластера и новый тег образа, который читает `LLM_API_KEY`. Одного наличия OpenAI-совместимого адаптера в старом образе недостаточно.

```sh
helm upgrade "${RELEASE:?Укажите имя релиза}" ./deploy/helm/themed-chat \
  --kube-context "${PROD_CONTEXT:?Укажите контекст прод-кластера}" \
  --namespace "${NAMESPACE:?Укажите namespace}" \
  --reuse-values \
  --set-string "llm.baseUrl=https://klinskoe17.frontierai.ru/v1" \
  --set-string "llm.model=glm-5.3-flash-cb" \
  --set-string "existingSecret=${RUNTIME_SECRET:?Укажите Secret с ключом Frontier AI}" \
  --set-string "image.tag=${IMAGE_TAG:?Укажите тег образа с LLM_API_KEY}" \
  --wait --timeout 5m
```

После обновления отправьте тестовый вопрос через чат: готовность Pod сама по себе не проверяет доступность модели и её ключ.

## API

| Запрос | Результат |
|---|---|
| `POST /api/session` с `X-Access-Key` | Выдаёт HttpOnly cookie (`204`) |
| `GET /api/session` | Проверяет сессию (`204`) |
| `GET /api/messages` | Заголовок и история (UTC) |
| `POST /api/messages` `{"text": "..."}` | Сохраняет пару реплик (`201`), до 500 символов |

## Устройство проекта

- [app.py](src/themed_chat/app.py) связывает зависимости; [api/](src/themed_chat/api/) проверяет ключ, обрабатывает гостевую сессию и запросы чата.
- [chat/](src/themed_chat/chat/) содержит сценарий чата. [adapters/](src/themed_chat/adapters/) подключает LLM и PostgreSQL: вызов модели выполняется вне транзакции, готовая пара реплик сохраняется вместе. Схема обновляется миграциями из [migrations/](src/themed_chat/migrations/).
- [web/](src/themed_chat/web/) — HTML, CSS и JavaScript без фреймворка.

## Проверки

Нужен отдельный тестовый PostgreSQL с правом `CREATEDB`; ключ провайдера не нужен.

```sh
docker run --rm -d --name themed-chat-test-db -e POSTGRES_PASSWORD=test-only -p 127.0.0.1:55432:5432 postgres:17-alpine
docker exec themed-chat-test-db pg_isready -h 127.0.0.1 -U postgres  # повторите, пока не ответит accepting
export TEST_POSTGRES_URL='postgresql+asyncpg://postgres:test-only@127.0.0.1:55432/postgres?ssl=disable'
make check   # lock, Ruff, mypy, документация, unit- и интеграционные тесты
uv run --locked --group browser playwright install chromium && make e2e
docker stop themed-chat-test-db
```

## Что можно доработать

- Пагинация истории, лимиты входа и генерации для публичного деплоя, мониторинг квот.
- Серверная идемпотентность: сейчас при потере ответа интерфейс лишь просит проверить историю перед повтором.
- Несколько реплик, резервное копирование и перенос данных между БД. Вместо общего ключа — индивидуальные учётные записи, если требуется личная история.

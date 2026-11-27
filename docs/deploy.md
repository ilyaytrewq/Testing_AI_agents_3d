---
title: "Развёртывание в Kubernetes"
description: "Установка приложения с Helm и настройка подключения к PostgreSQL и модели."
references:
  "../Dockerfile": "c597e20b082a2ad032d1574d653955fa8c4f9876ea17cbb6f6984e04ff2bf390"
  "../deploy/helm/themed-chat/Chart.yaml": "40212058339ec05ef383cef5c89b6f5cdcb036ebe1b799f5054a312a216e680f"
  "../deploy/helm/themed-chat/values.yaml": "3b5d6e68e795c3155e24d10c18fa0ca6b2562ba900d616086e98673f2b71b4e6"
  "../deploy/helm/themed-chat/templates/deployment.yaml": "024415d349fb0cd76b1c217e16056ec996f214c00a2bd0cbc04e83c54e1ab015"
  "../deploy/helm/themed-chat/templates/service.yaml": "c02ea24783b035be44fb5dd702b9572bad26fadb5839dd7f36d7a3c56b863c62"
---

# Развёртывание в Kubernetes

[Helm-чарт](../deploy/helm/themed-chat/Chart.yaml) ставит только приложение: `Deployment` с одной репликой (`Recreate`) и `ClusterIP` на порту 8000. PostgreSQL, Ingress и готовый образ — ваши: соберите [Dockerfile](../Dockerfile) и загрузите образ в свой реестр (для закрытого — `imagePullSecrets` в [values.yaml](../deploy/helm/themed-chat/values.yaml)).

Одна реплика — осознанное ограничение: лимиты попыток входа и сообщений хранятся в памяти процесса. Если масштабировать приложение, их нужно вынести в общее хранилище (см. «Что можно доработать» в [README](../README.md)).

## Секреты

Для продового PostgreSQL укажите полную строку подключения в `DATABASE_URL` существующего Secret (`existingSecret`). Если создаёте Secret из файла, подготовьте `$HOME/.config/themed-chat/runtime.env` с правами `0600` вне репозитория:

```dotenv
APP_ACCESS_KEY=<ключ-доступа-к-чату>
APP_SESSION_SECRET=<секрет-подписи-сессии>
DATABASE_URL=postgresql+asyncpg://user:password@host:5432/themed_chat?ssl=verify-full
LLM_API_KEY=<ключ-модели>
```

Чарт монтирует этот Secret томом только для чтения в `/run/secrets/themed-chat` (файлы с правами `0440` для группы приложения) и передаёт приложению пути в `APP_ACCESS_KEY_FILE`, `APP_SESSION_SECRET_FILE`, `DATABASE_URL_FILE` и `LLM_API_KEY_FILE`. Значения секретов не попадают в переменные окружения процесса и в `kubectl describe pod`.

Если классификатор темы работает через другой API (`classifier.baseUrl`) на другом хосте, добавьте в Secret ключ `CLASSIFIER_API_KEY` и задайте `classifier.apiKeyInSecret=true`: основной ключ на чужой хост не отправляется, без своего ключа приложение не запустится.

`APP_ACCESS_KEY` и `APP_SESSION_SECRET` должны отличаться. Смена `APP_ACCESS_KEY` завершает все действующие сессии: после перезапуска пользователям нужно войти заново.

URL API модели и её ID задаются вместе в `llm.baseUrl` и `llm.model` в [values.yaml](../deploy/helm/themed-chat/values.yaml) либо через `--set-string`. Если оба поля пусты, используются настройки из [config/app.yaml](../config/app.yaml). Подойдёт любой OpenAI-совместимый API, а `LLM_API_KEY` должен быть ключом именно этого сервиса.

## Установка

```sh
kubectl create namespace themed-chat
kubectl -n themed-chat create secret generic themed-chat-runtime --from-env-file="$HOME/.config/themed-chat/runtime.env"
helm upgrade --install coffee ./deploy/helm/themed-chat \
  --namespace themed-chat --wait --timeout 5m \
  --set-string image.repository=YOUR_REGISTRY/themed-chat \
  --set-string image.tag=0.1.0 --set-string existingSecret=themed-chat-runtime
kubectl -n themed-chat port-forward svc/coffee-themed-chat 8000:8000
```

## Что учесть

- Имя релиза: строчные латинские буквы, цифры и `-`, начинается с буквы.
- За внешним шлюзом задайте `publicOrigin` — точный HTTPS-адрес без пути и `/` на конце (`https://chat.example.com`). Для `127.0.0.1`/`localhost` достаточно совпадения схемы и порта; любой другой адрес сверяется точно. Для `port-forward` на другой порт тоже поменяйте `publicOrigin`.
- Лимит попыток входа считается по адресу клиента. За Ingress или балансировщиком приложение видит адрес прокси, поэтому без настройки все пользователи делят один лимит, и один перебирающий ключ клиент блокирует вход остальным. Укажите сети прокси в `trustedProxies` (например, `--set 'trustedProxies={10.0.0.0/8}'`, в приложение уходит как `APP_AUTH__TRUSTED_PROXIES`): только для соединений из этих сетей адресом клиента считается самый правый адрес в `X-Forwarded-For`, который сам не принадлежит прокси. Прокси должен дописывать адрес клиента в `X-Forwarded-For`, а не передавать присланный клиентом заголовок как есть.
- База PostgreSQL должна существовать, роль — уметь применять миграции Alembic. Из параметров `DATABASE_URL` допустим только `ssl`, спецсимволы в логине и пароле кодируйте (`$` → `%24`).
- Частный CA: Secret с ключом `ca.crt`, его имя — в `postgresCASecret`.
- Миграции идут при старте под advisory-блокировкой, параллельные Pod ждут друг друга.
- Проверки: `readinessProbe` и `startupProbe` обращаются к `/readyz` (приложение запущено и база отвечает), `livenessProbe` — к `/healthz` (процесс жив, база не проверяется, поэтому её сбой не перезапускает Pod).
- После правки Secret: `kubectl -n themed-chat rollout restart deployment/coffee-themed-chat`. `helm uninstall` не удаляет Secret и БД.

## Смена модели в действующем релизе

Передайте новые `llm.baseUrl` и `llm.model` вместе с Secret, в котором `LLM_API_KEY` — ключ нового сервиса. Адрес самого чата (`publicOrigin`) не меняется.

```sh
helm upgrade "${RELEASE:?Укажите имя релиза}" ./deploy/helm/themed-chat \
  --kube-context "${CONTEXT:?Укажите контекст кластера}" \
  --namespace "${NAMESPACE:?Укажите namespace}" \
  --reuse-values \
  --set-string "llm.baseUrl=${LLM_BASE_URL:?Укажите базовый URL API}" \
  --set-string "llm.model=${LLM_MODEL:?Укажите ID модели}" \
  --set-string "existingSecret=${RUNTIME_SECRET:?Укажите Secret с ключом новой модели}" \
  --wait --timeout 5m
```

После обновления отправьте тестовый вопрос через чат: готовность Pod сама по себе не проверяет доступность модели и её ключ.

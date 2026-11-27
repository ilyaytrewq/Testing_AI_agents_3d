---
title: "Развёртывание в Kubernetes"
description: "Установка Helm-чарта сервиса с отдельной PostgreSQL и готовым Kubernetes Secret."
references:
  "../Dockerfile": "4edbe16d83a4310ee20c86615801bd0213ccc1886f444eb4790e67aefc82a114"
  "../deploy/helm/themed-chat/Chart.yaml": "40212058339ec05ef383cef5c89b6f5cdcb036ebe1b799f5054a312a216e680f"
  "../deploy/helm/themed-chat/values.yaml": "8319d2568cddda49b60c87cf5257efd4e8e96195d95547d2e82f56578ac1e59a"
  "../deploy/helm/themed-chat/templates/deployment.yaml": "6211020632ca24b4cc4cda9db77a2dcd1d4c95c4884fa755ada23bfebcf39768"
  "../deploy/helm/themed-chat/templates/service.yaml": "c02ea24783b035be44fb5dd702b9572bad26fadb5839dd7f36d7a3c56b863c62"
---

# Развёртывание в Kubernetes

[Helm-чарт](../deploy/helm/themed-chat/Chart.yaml) устанавливает только приложение: один `Deployment` и внутренний `ClusterIP` на порту 8000. PostgreSQL и Ingress чарт не создаёт. Для запуска нужны кластер Kubernetes, `kubectl`, Helm, готовая PostgreSQL и доступный кластеру образ из [Dockerfile](../Dockerfile). Публикуемого образа по умолчанию нет: соберите образ, например `docker build -t YOUR_REGISTRY/themed-chat:0.1.0 .`, и загрузите его в свой реестр. Для закрытого реестра можно указать `imagePullSecrets` в [values.yaml](../deploy/helm/themed-chat/values.yaml).

## Установка

В namespace `themed-chat` заранее создайте Secret `themed-chat-runtime` с четырьмя ключами: `APP_ACCESS_KEY`, `APP_SESSION_SECRET`, `GEMINI_API_KEY`, `DATABASE_URL`. Можно подготовить отдельный файл `runtime.env` с этими ключами в формате `KEY=value` с правами `0600`; не кладите его в репозиторий, values или образ. Не используйте локальный Compose `.env` в качестве этого файла. Сгенерируйте независимые ключ доступа и секрет сессии, как описано в [README](../README.md).

```sh
kubectl create namespace themed-chat
kubectl -n themed-chat create secret generic themed-chat-runtime --from-env-file=runtime.env
helm upgrade --install coffee ./deploy/helm/themed-chat \
  --namespace themed-chat --wait --timeout 5m \
  --set-string image.repository=YOUR_REGISTRY/themed-chat \
  --set-string image.tag=0.1.0 --set-string existingSecret=themed-chat-runtime
kubectl -n themed-chat port-forward svc/coffee-themed-chat 8000:8000
```

Откройте `http://127.0.0.1:8000`. При доступе через внешний шлюз настройте маршрутизацию на этот Service и задайте `publicOrigin` равным точному HTTPS-адресу без пути и завершающего `/`, например `https://chat.example.com`. Для `port-forward` на другом порту поменяйте и `publicOrigin`, и адрес в браузере.

## Подключение к PostgreSQL

Формат `DATABASE_URL`: `postgresql+asyncpg://user:password@db.example.com:5432/themed_chat?ssl=verify-full`. Целевая база должна существовать, приниматься с сети Pod и позволять роли применить миграции Alembic. Кодируйте спецсимволы в имени и пароле для URL. По умолчанию `PGSSLROOTCERT` указывает на системный набор сертификатов образа. Если БД использует частный CA, создайте в том же namespace Secret с ключом `ca.crt` и укажите его имя в `postgresCASecret`; чарт примонтирует сертификат только для чтения.

Миграции выполняются при старте, поэтому чарт использует одну реплику и стратегию `Recreate`: при обновлении возможен короткий простой. Не запускайте несколько релизов приложения на одной БД во время миграций. При изменении значений в существующем Secret перезапустите Pod, например `kubectl -n themed-chat rollout restart deployment/coffee-themed-chat`. Удаление Helm-релиза не удаляет Secret и внешнюю БД.

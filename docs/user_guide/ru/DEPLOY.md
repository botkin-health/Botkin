# Деплой гайда на botkin.health/guide/

## Сервер

- Хост: `116.203.213.137`
- Пользователь: `root`
- Папка для статики: `/opt/botkin-site/guide/`
- nginx проксирует `botkin.health/guide/` на эту папку (конфиг — TODO, см. ниже).

## Получить SSH-пароль

```bash
op item get zmkx52ei6tzmlcclntwak4p3wi \
  --account my.1password.com \
  --fields password --reveal
```

## Сборка и заливка

Из `docs/user_guide/ru/`:

```bash
# 1. Собрать
mkdocs build

# 2. Залить (sshpass для неинтерактивного пароля)
SSHPASS=$(op item get zmkx52ei6tzmlcclntwak4p3wi \
  --account my.1password.com --fields password --reveal) \
/opt/homebrew/bin/sshpass -e rsync -avz --delete \
  site/ root@116.203.213.137:/opt/botkin-site/guide/
```

`--delete` подчистит файлы, которых уже нет в новом билде. Если страшно — уберите флаг.

## TODO для сайт-агента

nginx ещё не настроен на отдачу `/guide/`. Нужно:

1. Добавить в server block `botkin.health` location:

   ```nginx
   location /guide/ {
       alias /opt/botkin-site/guide/;
       index index.html;
       try_files $uri $uri/ $uri.html =404;
   }
   ```

2. Проверить `nginx -t` и `systemctl reload nginx`.
3. Убедиться, что `site_url` в `mkdocs.yml` совпадает с публичным URL (`https://botkin.health/guide/`).

Когда nginx настроен — деплой состоит из двух команд (build + rsync).

## Откат

Бэкап предыдущей версии перед заливкой:

```bash
ssh root@116.203.213.137 \
  "cp -r /opt/botkin-site/guide /opt/botkin-site/guide.bak.$(date +%Y%m%d-%H%M%S)"
```

Откатить — переименовать `guide.bak.*` обратно в `guide`.

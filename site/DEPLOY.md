# Deploy botkin.health

Сервер: Hetzner `116.203.213.137`, nginx уже стоит, Cloudflare проксирует TLS.

```bash
# 1. Залить статику
rsync -avz --delete site/ root@116.203.213.137:/opt/botkin-site/

# 2. Залить nginx-конфиг
scp site/nginx-botkin.health.conf root@116.203.213.137:/etc/nginx/sites-available/botkin.health

# 3. На сервере — включить и перезагрузить
ssh root@116.203.213.137 '
  ln -sf /etc/nginx/sites-available/botkin.health /etc/nginx/sites-enabled/botkin.health &&
  nginx -t &&
  systemctl reload nginx
'

# 4. Проверка
curl -I https://botkin.health
```

Cloudflare SSL mode должен быть **Flexible** или **Full** (не Full strict — origin без сертификата).

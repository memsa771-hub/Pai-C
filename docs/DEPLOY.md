# Deploying Placement AI (beta) to the Ubuntu server

This puts the whole stack on the AWS Ubuntu server that already serves
placement-ai.com, next to the website, behind the host's nginx:

```
browser --https--> nginx (host, ports 80/443)
                     |-- app.placement-ai.com  --> 127.0.0.1:3000  frontend  (Next.js)
                     |-- api.placement-ai.com  --> 127.0.0.1:8000  backend   (FastAPI)
                                                    worker, postgres, redis, qdrant (Docker network only)
```

Everything runs from `docker-compose.prod.yml`. The containers bind to
127.0.0.1 only, so nothing is reachable from the internet except through nginx.

## 0. Before you start

- Server: Ubuntu 22.04 or 24.04, at least 2 vCPU and 4 GB RAM (8 GB is
  comfortable), 25 GB free disk. The images take about 6 GB.
- AWS security group: inbound 80 and 443 open (22 for you). Nothing else.
- DNS: two A records pointing at the server's public (Elastic) IP:
  `app.placement-ai.com` and `api.placement-ai.com`. Check with
  `dig +short app.placement-ai.com` before requesting certificates.
- Keys at hand: OpenAI key, Anthropic key, Tavily key, Resend key, the Firebase
  web-app config and the Firebase service-account JSON (docs/AUTH_SESSION.md).

## 1. Install Docker (once)

```
sudo apt-get update && sudo apt-get install -y ca-certificates curl git
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
newgrp docker
docker compose version
```

If the server has 4 GB RAM or less, add swap so the first build does not run out of memory:

```
sudo fallocate -l 4G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

## 2. Get the code

```
git clone https://github.com/memsa771-hub/Pai-beta.git ~/pai-beta
cd ~/pai-beta
```

## 3. Secrets

```
cp .env.production.example .env
nano .env                      # fill every REQUIRED value
mkdir -p secrets proposals
nano secrets/firebase-service-account.json   # paste the service-account JSON
chmod 600 .env secrets/firebase-service-account.json
```

Do not set `APP_ENV`, `CORS_ORIGINS`, `APP_URL`, `FRONTEND_BASE_URL` or
`NEXT_PUBLIC_API_URL` in `.env`: the compose file sets the production values and
the backend refuses to start with anything else.

## 4. Build and start

```
docker compose -f docker-compose.prod.yml up -d --build
```

The first build takes 10 to 20 minutes (Chromium for the research browser, the
Next.js build). Then:

```
docker compose -f docker-compose.prod.yml ps        # backend (healthy), frontend, worker, postgres, redis, qdrant up; migrate exited 0
curl -s http://127.0.0.1:8000/health                # {"status": ...}
curl -sI http://127.0.0.1:3000 | head -1            # HTTP/1.1 200 OK
docker compose -f docker-compose.prod.yml logs --tail 50 migrate backend worker
```

Migrations run once in the `migrate` service before the backend starts; a new
release that adds migrations applies them the same way.

## 5. nginx and TLS

First see what already owns ports 80 and 443 on this server:

```
sudo ss -ltnp | grep -E ':80 |:443 '
```

- **nginx on the host** (usual case): continue below.
- **Apache**: either move the website to nginx, or add two Apache virtual hosts
  that `ProxyPass` to 127.0.0.1:3000 and 127.0.0.1:8000 with the same headers
  as the files in `deploy/nginx/`, then `certbot --apache`.
- **A Docker container holding 80/443** (a dockerised website): add the two
  server blocks to that container's nginx configuration instead, with the
  upstream being the host (`host.docker.internal` or the docker0 address) and
  the same ports.

With nginx on the host:

```
sudo apt-get install -y nginx certbot python3-certbot-nginx
sudo cp deploy/nginx/app.placement-ai.com.conf deploy/nginx/api.placement-ai.com.conf /etc/nginx/sites-available/
sudo ln -sf /etc/nginx/sites-available/app.placement-ai.com.conf /etc/nginx/sites-enabled/
sudo ln -sf /etc/nginx/sites-available/api.placement-ai.com.conf /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d app.placement-ai.com -d api.placement-ai.com --redirect
sudo nginx -t && sudo systemctl reload nginx
```

certbot rewrites the two files with the certificate paths and an HTTP to HTTPS
redirect, and installs a renewal timer (`systemctl list-timers | grep certbot`).

## 6. Firebase and Resend

- Firebase console, Authentication, Settings, Authorized domains: make sure
  `app.placement-ai.com` is listed (docs/AUTH_SESSION.md). Sign-in fails with
  `auth/unauthorized-domain` otherwise.
- Resend: the domain in `EMAIL_FROM` is verified, and `RESEND_API_KEY` belongs
  to it. Account emails (verify, reset, new sign-in) link to
  `https://app.placement-ai.com/auth/action`.

## 7. Verify live

```
curl -s https://api.placement-ai.com/health
curl -sI https://app.placement-ai.com | head -1
```

Then in a browser: open https://app.placement-ai.com, sign in with a fresh
account, complete onboarding, and check that the opening message arrives and
that a chat reply comes back in your language. The Profile page shows the Vault
filling; the Mirror and Paths pages appear once the Vault has a goal and two
interests. Spend: `GET https://api.placement-ai.com/v1/admin/usage` with a
signed-in founder account (the Settings page shows the same card).

## 8. Day to day

Update to a new release:

```
cd ~/pai-beta && git pull && docker compose -f docker-compose.prod.yml up -d --build
```

Only the images whose source changed are rebuilt; data in the volumes
(`pgdata`, `qdrant_data`, `files`) is kept.

Logs and status:

```
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs -f backend worker
docker compose -f docker-compose.prod.yml restart backend worker frontend
```

Backups (the database is the only thing that cannot be rebuilt):

```
sh scripts/backup-postgres.sh        # writes backups/openagents_workspace_<timestamp>.dump
```

Run it daily from cron and copy the files off the server (S3 or your machine):

```
(crontab -l 2>/dev/null; echo "15 3 * * * cd $HOME/pai-beta && sh scripts/backup-postgres.sh >> backups/backup.log 2>&1") | crontab -
```

Restore: `docker compose -f docker-compose.prod.yml exec -T postgres pg_restore -U pai_admin -d openagents_workspace --clean --if-exists < backups/<file>.dump`.

Roll back a release: `git checkout <previous commit>` then `up -d --build`.
Migrations are forward-only; if a release's migration must be undone, restore
the backup taken before the update.

Spend and the monthly cap, evals and the rules refresh: docs/counselor/BETA_RUNBOOK.md.

## 9. If something is wrong

| Symptom | Cause and fix |
| --- | --- |
| `backend` exits: "Production CORS_ORIGINS must be exactly https://app.placement-ai.com" | `.env` overrides `CORS_ORIGINS`. Remove the line. |
| `backend` exits: "DB_PASSWORD must be set" or a Firebase variable is missing | Fill the REQUIRED values in `.env`. |
| Sign-in page shows `auth/unauthorized-domain` | Add `app.placement-ai.com` to Firebase authorized domains. |
| App loads, every request fails with a network or CORS error | The frontend image was built with another API origin. `docker compose -f docker-compose.prod.yml build --no-cache frontend && docker compose -f docker-compose.prod.yml up -d frontend`. |
| 502 from nginx | The container is not healthy: `docker compose -f docker-compose.prod.yml ps`, then its logs. |
| Build killed, "exit code 137" | Out of memory: add swap (section 1) and rerun. |
| Disk full | `docker system prune -f` removes old images and build cache; volumes are kept. |
| Replies say PAI is paused | The monthly cap (`PAI_MONTHLY_CAP_USD`) is reached; see BETA_RUNBOOK section 4. |

# Deploying Placement AI (beta) to the Ubuntu server

This puts the whole stack on the AWS Ubuntu server that already serves
placement-ai.com, next to the website, behind the host's reverse proxy (Caddy, or nginx):

```
browser --https--> Caddy or nginx (host, ports 80/443)
                     |-- app.placement-ai.com  --> 127.0.0.1:3000  frontend  (Next.js)
                     |-- api.placement-ai.com  --> 127.0.0.1:8000  backend   (FastAPI)
                                                    worker, postgres, redis, qdrant (Docker network only)
```

Everything runs from `docker-compose.prod.yml`. The containers bind to
127.0.0.1 only, so nothing is reachable from the internet except through the proxy.

## 0. Before you start

- Server: Ubuntu 22.04 or 24.04, at least 2 vCPU and 4 GB RAM (8 GB is
  comfortable), 25 GB free disk. The images take about 6 GB.
- AWS security group: inbound 80 and 443 open (22 for you). Nothing else.
- DNS: two A records pointing at the server's public (Elastic) IP:
  `app.placement-ai.com` and `api.placement-ai.com`. Check with
  `dig +short app.placement-ai.com` before requesting certificates.
  On Cloudflare: DNS, Records, Add record, Type A, Name `app` (then `api`),
  IPv4 address = the server IP, Proxy status **DNS only** (grey cloud), TTL
  Auto. Keep both records DNS only: Caddy then issues the certificates itself
  and no Cloudflare proxy timeout (100 s) sits in front of long requests.
  Turning the orange cloud on later is possible once the certificates exist
  (SSL/TLS mode Full (strict)), but it is not needed for the beta.
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
git clone https://github.com/memsa771-hub/Pai-beta.git ~/pai-c
cd ~/pai-c
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

The stack joins the reverse proxy's Docker network (`proxy` in the compose
file). With a proxy on the host (Caddy or nginx installed on Ubuntu) create an
empty one once:

```
docker network create pai-beta_proxy
```

With a proxy that runs in Docker (the website's `caddy` container), skip that
and set `PROXY_NETWORK` in `.env` to the proxy's network instead (section 5).
If something on this server already listens on port 3000 (a website container
does), set `FRONTEND_PORT=3001` in `.env` as well.

```
docker compose -f docker-compose.prod.yml up -d --build
```

The first build takes 10 to 20 minutes (Chromium for the research browser, the
Next.js build). Then:

```
docker compose -f docker-compose.prod.yml ps        # backend (healthy), frontend, worker, postgres, redis, qdrant up; migrate exited 0
curl -s http://127.0.0.1:8000/health                # {"status": ...}
curl -sI http://127.0.0.1:3000 | head -1            # HTTP/1.1 200 OK (3001 when FRONTEND_PORT=3001)
docker compose -f docker-compose.prod.yml logs --tail 50 migrate backend worker
```

Migrations run once in the `migrate` service before the backend starts; a new
release that adds migrations applies them the same way.

## 5. Reverse proxy and TLS: Caddy (or nginx)

First see what already owns ports 80 and 443 on this server:

```
sudo ss -ltnp | grep -E ':80 |:443 '
```

### Caddy on the host (the website already runs on Caddy)

Caddy gets and renews the certificates itself; no certbot. Append the two site
blocks from `deploy/caddy/Caddyfile` to the existing Caddyfile, keeping the
website's own block:

```
sudo sh -c 'cat deploy/caddy/Caddyfile >> /etc/caddy/Caddyfile'
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
sudo journalctl -u caddy --since "2 min ago" --no-pager | tail -20   # certificate obtained for both names
```

If Caddy is not installed yet:

```
sudo apt-get install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt-get update && sudo apt-get install -y caddy
sudo cp deploy/caddy/Caddyfile /etc/caddy/Caddyfile      # add the website's block to it as well
sudo systemctl enable --now caddy
```

### Caddy in a Docker container (the website's caddy container)

The stack joins the caddy container's network and Caddy reaches it as
`pai-frontend:3000` and `pai-backend:8000`; no host ports are involved.

1. Find the network and the Caddyfile that container uses:

   ```
   docker inspect pai-website-caddy-1 --format '{{range $k, $v := .NetworkSettings.Networks}}{{$k}}{{"
"}}{{end}}'
   docker inspect pai-website-caddy-1 --format '{{range .Mounts}}{{.Source}} -> {{.Destination}}{{"
"}}{{end}}'
   ```

   The first prints the network (for example `pai-website_default`); the
   second shows where the Caddyfile lives on the host (the mount whose
   destination is `/etc/caddy/Caddyfile`).

2. In `~/pai-c/.env` set `PROXY_NETWORK=<that network>` and
   `FRONTEND_PORT=3001` (the website holds 3000), then
   `docker compose -f docker-compose.prod.yml up -d --build` (section 4).

3. Append the blocks from `deploy/caddy/Caddyfile.docker` to the website's
   Caddyfile (the host path from step 1) and reload:

   ```
   sudo sh -c 'cat ~/pai-c/deploy/caddy/Caddyfile.docker >> <host path of the Caddyfile>'
   docker exec pai-website-caddy-1 caddy validate --config /etc/caddy/Caddyfile
   docker exec pai-website-caddy-1 caddy reload --config /etc/caddy/Caddyfile
   docker logs --since 2m pai-website-caddy-1 2>&1 | tail -20      # certificates obtained for both names
   ```

   The website's own block stays as it is. The container names above are the
   website project's; `docker ps` shows them.

### nginx on the host instead

```
sudo apt-get install -y nginx certbot python3-certbot-nginx
sudo cp deploy/nginx/app.placement-ai.com.conf deploy/nginx/api.placement-ai.com.conf /etc/nginx/sites-available/
sudo ln -sf /etc/nginx/sites-available/app.placement-ai.com.conf /etc/nginx/sites-enabled/
sudo ln -sf /etc/nginx/sites-available/api.placement-ai.com.conf /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d app.placement-ai.com -d api.placement-ai.com --redirect
sudo nginx -t && sudo systemctl reload nginx
```

Caddy and nginx cannot both hold ports 80 and 443: use the one the website
already uses.

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
cd ~/pai-c && git pull && docker compose -f docker-compose.prod.yml up -d --build
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
(crontab -l 2>/dev/null; echo "15 3 * * * cd $HOME/pai-c && sh scripts/backup-postgres.sh >> backups/backup.log 2>&1") | crontab -
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
| Caddy log: certificate for app/api not obtained | DNS does not point at this server yet, or 80/443 are not open in the security group. Fix, then `sudo systemctl reload caddy`. |
| Sign-in page shows `auth/unauthorized-domain` | Add `app.placement-ai.com` to Firebase authorized domains. |
| App loads, every request fails with a network or CORS error | The frontend image was built with another API origin. `docker compose -f docker-compose.prod.yml build --no-cache frontend && docker compose -f docker-compose.prod.yml up -d frontend`. |
| `network pai-beta_proxy declared as external, but could not be found` | Host proxy: `docker network create pai-beta_proxy`. Docker proxy: set `PROXY_NETWORK` in `.env` to the proxy's network. |
| `Bind for 127.0.0.1:3000 failed: port is already allocated` | Another container holds 3000: set `FRONTEND_PORT=3001` in `.env` and run `up -d` again. |
| 502 from Caddy or nginx | The container is not healthy: `docker compose -f docker-compose.prod.yml ps`, then its logs. |
| Build killed, "exit code 137" | Out of memory: add swap (section 1) and rerun. |
| Disk full | `docker system prune -f` removes old images and build cache; volumes are kept. |
| Replies say PAI is paused | The monthly cap (`PAI_MONTHLY_CAP_USD`) is reached; see BETA_RUNBOOK section 4. |

# Bob Labs — Production Installation Guide

Production deployment on a dedicated server (e.g. `192.168.1.101`), with GPU agents reporting to both prod and dev control planes.

## Architecture Overview

```
Internet → Router (port forward 80/443 TCP → 192.168.1.101:80)
               │
        ┌──────▼──────┐
        │  Nginx (host)│  :80/:443
        │  certbot SSL │
        └──────┬───────┘
               │
    ┌──────────┼──────────────────┐
    │          │ Docker network    │
    │   ┌──────▼──────┐           │
    │   │   bob-ui    │ :3000     │
    │   │ (frontend)  │           │
    │   └──────┬──────┘           │
    │          │ /api/ /ws/       │
    │   ┌──────▼──────┐           │
    │   │  bob-api    │ :8888     │  ◄── GPU agents connect here (WS :8888)
    │   └──────┬──────┘           │
    │          │                  │
    │   ┌──────▼──────┐           │
    │   │   bob-db    │ :5435     │
    │   └─────────────┘           │
    └─────────────────────────────┘
```

**Ports used:**
| Port  | Service           | Exposed to       |
|-------|-------------------|------------------|
| 80    | Nginx (HTTP→HTTPS redirect) | Public  |
| 443   | Nginx (HTTPS)     | Public           |
| 3000  | bob-ui (frontend) | localhost only (behind nginx) |
| 8888  | bob-api (FastAPI)  | LAN only (agents + nginx) |
| 5435  | PostgreSQL         | localhost only   |

---

## 1. Server Setup — User & Permissions

SSH into the prod server:

```bash
ssh your-user@192.168.1.101
```

### 1.1 Create the service user

```bash
# Create user with home directory
sudo adduser boblab

# Add to required groups
sudo usermod -aG sudo boblab       # sudo access for setup
sudo usermod -aG docker boblab     # docker access

# If docker group doesn't exist yet (docker not installed):
# It will be created during Docker installation
```

### 1.2 Install Docker

```bash
# Install Docker (if not already installed)
sudo apt update
sudo apt install -y ca-certificates curl gnupg lsb-release

sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Add boblab to docker group (if not done above)
sudo usermod -aG docker boblab

# Verify
sudo systemctl enable docker
docker --version
```

### 1.3 Install Git & clone the project

```bash
# Switch to boblab
su - boblab

# Install git if needed
sudo apt install -y git

# Clone
git clone <your-repo-url> ~/bob-manager
cd ~/bob-manager
```

---

## 2. Configure the Application

### 2.1 Create the `.env` file

```bash
cd ~/bob-manager
cp .env.example .env
```

Edit `.env` with **strong production values**:

```bash
nano .env
```

```env
# ── Database (use strong password) ─────────────
POSTGRES_USER=bobmanager
POSTGRES_PASSWORD=<GENERATE: openssl rand -base64 32>
POSTGRES_DB=bobmanager

# ── Security (generate unique secrets) ─────────
AGENT_SECRET=<GENERATE: openssl rand -hex 32>
JWT_SECRET=<GENERATE: openssl rand -hex 32>
JWT_ALGORITHM=HS256
JWT_EXPIRE_MINUTES=1440

# ── Admin bootstrap ───────────────────────────
ADMIN_SECRET=<GENERATE: openssl rand -hex 32>
ADMIN_EMAIL=your-email@example.com
APP_BASE_URL=https://your-domain.com

# ── Network Binding ────────────────────────────
# Bind internal services to localhost (behind nginx)
BIND_ADDR=127.0.0.1

# ── SMTP (optional, for trials/notifications) ─
# SMTP_HOST=smtp.example.com
# SMTP_PORT=587
# SMTP_USER=...
# SMTP_PASSWORD=...
# SMTP_FROM=bob@your-domain.com
# SMTP_TLS=true
```

Generate all secrets at once:

```bash
echo "POSTGRES_PASSWORD=$(openssl rand -base64 32)"
echo "AGENT_SECRET=$(openssl rand -hex 32)"
echo "JWT_SECRET=$(openssl rand -hex 32)"
echo "ADMIN_SECRET=$(openssl rand -hex 32)"
```

### 2.2 Build and start

```bash
cd ~/bob-manager
docker compose build
docker compose up -d
```

Verify:

```bash
docker compose ps          # All services healthy
curl -s http://localhost:3000  # Frontend responds
curl -s http://localhost:8888/api/v1/public/health  # API responds (if health endpoint exists)
```

---

## 3. Nginx Reverse Proxy (Host-level)

Install nginx on the host (not in Docker):

```bash
sudo apt install -y nginx
```

### 3.1 Create site config

```bash
sudo nano /etc/nginx/sites-available/bob-manager
```

```nginx
# HTTP → HTTPS redirect (enabled after certbot)
server {
    listen 80;
    server_name your-domain.com;

    # Certbot challenge
    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    # Redirect all other traffic to HTTPS (uncomment after certbot)
    # location / {
    #     return 301 https://$host$request_uri;
    # }

    # Temporary: proxy to app before SSL is set up
    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        client_max_body_size 25m;
    }
}
```

Enable and test:

```bash
sudo ln -sf /etc/nginx/sites-available/bob-manager /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl reload nginx
```

---

## 4. SSL with Certbot

### 4.1 Router Port Forwarding

On your router, forward **TCP only** (no UDP needed for HTTP/HTTPS):

| External Port | Internal IP      | Internal Port | Protocol |
|---------------|------------------|---------------|----------|
| 80            | 192.168.1.101    | 80            | TCP      |
| 443           | 192.168.1.101    | 443           | TCP      |

> **TCP only** — HTTPS and HTTP are TCP protocols. No UDP needed.

### 4.2 DNS

Point your domain to your public IP:
```
your-domain.com  →  A record  →  <your-public-ip>
```

If you don't have a static IP, use a Dynamic DNS service (e.g. DuckDNS, No-IP, Cloudflare tunnel).

### 4.3 Install Certbot & get certificate

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo mkdir -p /var/www/certbot

sudo certbot --nginx -d your-domain.com
```

**`certbot --nginx` edits your site file in place** — you don't need to manually
rewrite it afterwards. It does three things:

1. Adds a new `server { listen 443 ssl ... }` block with the right
   `ssl_certificate` paths.
2. Injects a `return 301 https://$host$request_uri;` into the existing
   port-80 block so plain HTTP gets redirected.
3. Reloads nginx.

You'll see `# managed by Certbot` annotations on the lines it touched.
Confirm with:

```bash
sudo cat /etc/nginx/sites-available/bob-manager
sudo nginx -t
```

Then refine the generated HTTPS block — add security headers, the
`/api/` location, the `/ws/client` WebSocket location — until it
matches the production-ready shape below:

```nginx
# HTTP → HTTPS redirect (certbot injected the `return 301` into this block)
server {
    listen 80;
    server_name your-domain.com;

    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    location / {
        return 301 https://$host$request_uri;
    }
}

# HTTPS — main config (certbot created this block; flesh out with security
# headers + API/WebSocket locations as needed)
server {
    listen 443 ssl http2;
    server_name your-domain.com;

    ssl_certificate /etc/letsencrypt/live/your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;
    include /etc/letsencrypt/options-ssl-nginx.conf;
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;

    client_max_body_size 25m;

    # Security headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;

    # ── Frontend (React SPA) ──
    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # ── API proxy ──
    location /api/ {
        proxy_pass http://127.0.0.1:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
    }

    # ── Client WebSocket (browser) ──
    location /ws/client {
        proxy_pass http://127.0.0.1:3000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 86400s;
    }
}
```

> **Note:** We proxy everything through `bob-ui` (port 3000) because the frontend nginx already handles routing to the API. This avoids duplicating auth logic.
>
> The agent WebSocket (port 8888) is **NOT** exposed through the public nginx — agents connect on the LAN directly.

### 4.6 Adding additional domains

The same host can serve multiple domains (e.g. the bob-manager admin UI at
`lab.boblabs.eu`, the public showroom at `showroom.boblabs.eu`, the marketing
landing at `boblabs.eu`, vanity domains like `cryptobob.fr` that surface a
single showroom app at root). Every public domain follows the same pattern.

**Convention: one file per domain in `/etc/nginx/sites-available/<domain>`.**
Don't mix multiple `server_name`s into a single file — it makes certbot's
edits harder to track and complicates per-domain proxy targets.

#### Container port reference

| Container         | Host port | What it serves                                    |
|-------------------|-----------|---------------------------------------------------|
| `bob-ui`          | 3000      | bob-manager admin UI + bob-api                    |
| `showroom-ui`     | 4000      | Public showroom SPA + showroom-api (`/api/`, `/og/`, `/static/`) |
| `boblabs_landing` | 8081      | boblabs.eu marketing landing                      |

#### Step-by-step

1. **DNS** — point `<domain>` to your public IP with an **A record**, not your
   registrar's "redirect" feature. Registrar-level redirects terminate at the
   registrar's edge, which means certbot on your server can't issue a
   certificate for that hostname and HTTPS will never work.

2. **Create the site config — HTTP block only at first.** Do not reference
   the cert paths yet — they don't exist, and `nginx -t` would refuse to
   reload. Include both the certbot challenge location and a temporary
   `proxy_pass` so the domain actually serves something during the cert
   issuance window:

   ```nginx
   # /etc/nginx/sites-available/<domain>
   server {
       listen 80;
       server_name <domain> www.<domain>;

       location /.well-known/acme-challenge/ {
           root /var/www/certbot;
       }

       location / {
           proxy_pass http://127.0.0.1:<container-port>;
           proxy_http_version 1.1;
           proxy_set_header Host              $host;
           proxy_set_header X-Real-IP         $remote_addr;
           proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
           proxy_set_header X-Forwarded-Proto $scheme;
           proxy_read_timeout 120s;
       }
   }
   ```

3. **Enable + reload:**

   ```bash
   sudo ln -s /etc/nginx/sites-available/<domain> /etc/nginx/sites-enabled/
   sudo nginx -t && sudo systemctl reload nginx
   ```

4. **Issue the cert — certbot edits the file in place:**

   ```bash
   sudo certbot --nginx -d <domain> -d www.<domain>
   ```

   You'll see new `# managed by Certbot` annotations: a fresh HTTPS `server`
   block with the right `ssl_certificate` paths, and a `301 https://...`
   redirect injected into the original port-80 block. Don't manually
   rewrite the file — let certbot own its edits.

5. **Verify:**

   ```bash
   curl -I https://<domain>/      # HTTP/2 200, no cert error
   curl -I http://<domain>/       # 301 → https
   ```

#### Vanity domain (one app at root path)

When the new domain should serve a *specific* showroom app at its root
(e.g. `cryptobob.fr/` shows the crypto-predictions tracker, no Bob Labs
catalog), the nginx-side work is identical to the steps above
(`proxy_pass http://127.0.0.1:4000`). The remaining changes are
SPA + SEO renderer side:

- Make the React SPA hostname-aware so `/` renders the target app under the
  vanity hostname. See the `IS_CRYPTOBOB` pattern in
  `showroom-ui/src/App.js`.
- Make the share-URL builders drop the `/app/<slug>` prefix when running
  under the vanity host (see `ChannelCardModal.js` /
  `LeaderboardTab.js` for the pattern).
- Thread the `Host` header into the SEO renderer so crawler-facing
  `og:url` / `<link rel="canonical">` advertise the vanity domain
  (`showroom-api/app/api/routes/seo.py` reads `Host` and passes it to
  `render_for_path`, which forwards it to the per-app renderers).

### 4.4 Defense-in-depth: rate limits + body caps (OP02)

The `/api/v1/internal/apps/*` surface accepts HMAC-signed consumer-app
traffic. The HMAC verifier rejects bad requests on the application
side, but the cheap denial-of-service is to spam the route with junk
payloads or unsigned bodies that still consume CPU during signature
verification.

Add the following to the **inside** of the `server { listen 443 … }`
block before any `location` directives, then put a per-location
`limit_req` on `/api/v1/internal/apps/`:

```nginx
# Rate-limit pool for the consumer-app surface. 10 req/s with a 20-burst.
# Pre-fix this was undocumented and operators were relying on the FastAPI
# layer to absorb everything.
limit_req_zone $binary_remote_addr zone=consumer_apps:10m rate=10r/s;

# (inside server block) ──

# Tight body cap for the HMAC envelope — bigger payloads are always wrong.
location /api/v1/internal/apps/ {
    limit_req zone=consumer_apps burst=20 nodelay;
    client_max_body_size 2m;          # HMAC payload + envelope, never larger
    proxy_pass http://127.0.0.1:3000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}

# Same idea for /api/v1/public/blog — it accepts inbound blog POSTs and
# the cluster K + D06 fixes make identity binding tight, but a body cap
# is still cheap insurance.
location /api/v1/public/blog {
    limit_req zone=consumer_apps burst=5 nodelay;
    client_max_body_size 1m;
    proxy_pass http://127.0.0.1:3000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

Adjust the rate to match your real consumer-app fan-in.

Test and reload:

```bash
sudo nginx -t
sudo systemctl reload nginx
```

### 4.5 Showroom env-var hygiene (OP05)

`showroom-api` lives in its own compose stack and reads two `.env`
files: the top-level `.env` (shared `JWT_SECRET`, DB URL, etc.) and
`showroom-api/.env` (showroom-specific OAuth / SMTP / app keys). The
drift hazard is that operators rotate `JWT_SECRET` in the top-level
`.env` and forget the showroom copy still has the old value — JWTs
issued by bob-api start failing in showroom-api with a generic 401.

Recommended layout:

```text
bob-manager/
  .env                  # JWT_SECRET, AGENT_SECRET, DB creds — single source of truth
  showroom-api/
    .env                # ONLY showroom-specific vars (OAuth, SMTP, Cloudflare key, etc.)
                        # NEVER copy JWT_SECRET here — load it via the compose file
```

In `showroom-api`'s compose service, inject the shared secrets from
the top-level `.env` via `env_file:`:

```yaml
# docker-compose.yml (top-level)
services:
  showroom-api:
    env_file:
      - ./.env                  # shared secrets (JWT_SECRET, DB_URL, …)
      - ./showroom-api/.env     # showroom-only vars
    # ↑ second file's keys win on conflict; keep them disjoint to avoid
    #   surprises.
```

This way `JWT_SECRET` exists in exactly one place on disk and the
showroom-api process reads the same value as bob-api / bob-ui.
Audit periodically with:

```bash
grep -H '^JWT_SECRET=' .env showroom-api/.env
# Should print exactly ONE line (the top-level .env).
```

### 4.4 Auto-renewal

Certbot installs a systemd timer automatically. Verify:

```bash
sudo systemctl status certbot.timer
sudo certbot renew --dry-run
```

---

## 5. UFW Firewall

```bash
sudo apt install -y ufw

# Default: deny incoming, allow outgoing
sudo ufw default deny incoming
sudo ufw default allow outgoing

# SSH (keep access!)
sudo ufw allow ssh

# HTTP/HTTPS (public)
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp

# Agent WebSocket — LAN only (GPU servers connect on port 8888)
sudo ufw allow from 192.168.1.0/24 to any port 8888 proto tcp

# Enable
sudo ufw enable
sudo ufw status verbose
```

Expected output:
```
To                         Action      From
--                         ------      ----
22/tcp                     ALLOW       Anywhere
80/tcp                     ALLOW       Anywhere
443/tcp                    ALLOW       Anywhere
8888/tcp                   ALLOW       192.168.1.0/24
9090/tcp                   ALLOW       192.168.1.0/24
3001/tcp                   ALLOW       192.168.1.0/24
```

---

## 6. Fail2Ban

```bash
sudo apt install -y fail2ban
```

### 6.1 Create local config

```bash
sudo nano /etc/fail2ban/jail.local
```

```ini
[DEFAULT]
# Ban for 1 hour, 5 failures in 10 minutes
bantime  = 3600
findtime = 600
maxretry = 5

# Whitelist LAN + dev server
ignoreip = 127.0.0.1/8 ::1 192.168.1.0/24

# Email notifications (optional, requires sendmail/msmtp)
# destemail = your-email@example.com
# sender = fail2ban@your-domain.com
# action = %(action_mwl)s

[sshd]
enabled  = true
port     = ssh
logpath  = /var/log/auth.log
maxretry = 3
bantime  = 3600

[nginx-http-auth]
enabled  = true
port     = http,https
logpath  = /var/log/nginx/error.log
maxretry = 5

[nginx-botsearch]
enabled  = true
port     = http,https
logpath  = /var/log/nginx/access.log
maxretry = 2
bantime  = 86400

[nginx-limit-req]
enabled  = true
port     = http,https
logpath  = /var/log/nginx/error.log
maxretry = 10
```

> **`ignoreip = 192.168.1.0/24`** whitelists the entire LAN including `192.168.1.102` (dev server) and all GPU agents. They will never get banned.

### 6.2 Start

```bash
sudo systemctl enable fail2ban
sudo systemctl start fail2ban

# Verify
sudo fail2ban-client status
sudo fail2ban-client status sshd
```

---

## 7. Additional Security Hardening

### 7.1 Bind Docker ports to localhost

By default, Docker bypasses UFW (it manipulates iptables directly). To prevent Docker from exposing ports publicly, `docker-compose.yml` uses the `BIND_ADDR` env var.

In your prod `.env`, ensure this line is set:

```env
BIND_ADDR=127.0.0.1
```

This binds the DB and frontend to localhost only. The API (port 8888) stays on all interfaces so GPU agents can connect from the LAN.

**⚠️ This is critical.** Without `BIND_ADDR=127.0.0.1`, Docker will expose these ports on all interfaces regardless of UFW rules.

Verify after starting:

```bash
sudo ss -tlnp | grep docker
# Should show:
#   127.0.0.1:3000   (bob-ui)
#   127.0.0.1:5435   (bob-db)
#   0.0.0.0:8888     (bob-api — LAN accessible)
```

> **Note:** Do NOT use `docker-compose.override.yml` for port bindings — Docker Compose merges (appends) ports from overrides, causing duplicate-bind conflicts.

### 7.2 SSH Hardening

```bash
sudo nano /etc/ssh/sshd_config
```

Ensure these values:
```
PermitRootLogin no
PasswordAuthentication no          # Use SSH keys only
MaxAuthTries 3
AllowUsers boblab your-user        # Only allow specific users
```

```bash
# Set up SSH key for boblab (from your workstation)
ssh-copy-id boblab@192.168.1.101

# Restart SSH
sudo systemctl restart sshd
```

### 7.3 Automatic security updates

```bash
sudo apt install -y unattended-upgrades
sudo dpkg-reconfigure -plow unattended-upgrades
```

### 7.4 Disable Docker socket exposure (if not needed)

The control plane mounts `/var/run/docker.sock` for sandbox container management. If you don't use sandboxed labs on the prod server, remove this line from `docker-compose.yml`:

```yaml
# Remove if not needed:
- /var/run/docker.sock:/var/run/docker.sock
```

---

## 8. GPU Agent Configuration

On each GPU server, configure the agent to connect to **both** control planes:

```bash
sudo nano /etc/bob-agent.env
```

```env
AGENT_NAME=gpu-server-name
CONTROL_PLANE_URL=ws://192.168.1.101:8888/ws/agent,ws://192.168.1.102:8888/ws/agent
AGENT_SECRET=<same-agent-secret-as-prod-.env>
```

> **Important:** The `AGENT_SECRET` on each GPU agent must match the `AGENT_SECRET` in the prod `.env`. If prod and dev use different secrets, the agent needs the prod secret (it sends the same token to both, so both control planes must accept the same token, OR you need to align the secrets).

Re-install and restart:
```bash
cd ~/bob-manager/agent
git pull
sudo bash install.sh
sudo systemctl restart bob-agent
journalctl -fu bob-agent
```

You should see:
```
Control Planes: ws://192.168.1.101:8888/ws/agent, ws://192.168.1.102:8888/ws/agent
Connecting to ws://192.168.1.101:8888/ws/agent ...
Connecting to ws://192.168.1.102:8888/ws/agent ...
Registered with control plane as 'gpu-server-name'
Registered with control plane as 'gpu-server-name'
```

---

## 9. Pre-flight Checklist

Run through this before going live:

- [ ] **Secrets**: All secrets in `.env` are unique, random, and strong (not defaults)
- [ ] **SSL**: `curl -I https://your-domain.com` returns 200 with valid cert
- [ ] **HTTP redirect**: `curl -I http://your-domain.com` returns 301 → https
- [ ] **UFW active**: `sudo ufw status` shows only expected ports
- [ ] **Fail2ban running**: `sudo fail2ban-client status` shows active jails
- [ ] **Docker ports bound**: `sudo ss -tlnp | grep docker` — only 8888 on 0.0.0.0, others on 127.0.0.1
- [ ] **SSH key-only**: `ssh -o PasswordAuthentication=yes boblab@192.168.1.101` is rejected
- [ ] **DB not exposed**: `nmap -p 5435 192.168.1.101` from another machine shows filtered/closed
- [ ] **Agent connects**: Both prod and dev control planes show the GPU servers online
- [ ] **Certbot renewal**: `sudo certbot renew --dry-run` succeeds
- [ ] **Backups**: Set up PostgreSQL backups (see below)

---

## 10. Backups (Recommended)

### PostgreSQL daily backup

```bash
sudo mkdir -p /opt/backups/bob-db
sudo chown boblab:boblab /opt/backups/bob-db
```

Create backup script:

```bash
nano ~/bob-manager/backup-db.sh
```

```bash
#!/bin/bash
BACKUP_DIR="/opt/backups/bob-db"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
docker exec bob-db pg_dump -U bobmanager bobmanager | gzip > "$BACKUP_DIR/bob-db_$TIMESTAMP.sql.gz"
# Keep last 30 days
find "$BACKUP_DIR" -name "*.sql.gz" -mtime +30 -delete
echo "Backup done: bob-db_$TIMESTAMP.sql.gz"
```

```bash
chmod +x ~/bob-manager/backup-db.sh
```

Add cron (as boblab):

```bash
crontab -e
```

```
# Daily DB backup at 3 AM
0 3 * * * /home/boblab/bob-manager/backup-db.sh >> /opt/backups/bob-db/backup.log 2>&1
```

---

## Quick Reference — Full Command Sequence

```bash
# === On 192.168.1.101 ===

# 1. User
sudo adduser boblab
sudo usermod -aG sudo,docker boblab
su - boblab

# 2. Docker (if not installed)
sudo apt update && sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# 3. Clone & configure
git clone <repo-url> ~/bob-manager
cd ~/bob-manager
cp .env.example .env
nano .env                          # Set all secrets

# 4. Build & start
docker compose build
docker compose up -d

# 5. Set BIND_ADDR in .env to lock ports to localhost — see §7.1
echo 'BIND_ADDR=127.0.0.1' >> .env

# 6. Nginx
sudo apt install -y nginx
sudo nano /etc/nginx/sites-available/bob-manager
sudo ln -sf /etc/nginx/sites-available/bob-manager /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx

# 7. SSL
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d your-domain.com
sudo nano /etc/nginx/sites-available/bob-manager   # Finalize config
sudo nginx -t && sudo systemctl reload nginx

# 8. Firewall
sudo apt install -y ufw
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow ssh
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw allow from 192.168.1.0/24 to any port 8888 proto tcp
sudo ufw enable

# 9. Fail2ban
sudo apt install -y fail2ban
sudo nano /etc/fail2ban/jail.local  # See §6.1
sudo systemctl enable --now fail2ban

# 10. SSH hardening
sudo nano /etc/ssh/sshd_config      # See §7.2
sudo systemctl restart sshd

# 11. Auto-updates
sudo apt install -y unattended-upgrades
sudo dpkg-reconfigure -plow unattended-upgrades
```

---

## 11. GPU Services Deployment

GPU services (MusicGen, Bark, RVC, CoquiTTS, STT, LTX-Video, Wan-Video) run on GPU servers alongside the agent. See [GPU_SERVICES.md](GPU_SERVICES.md) for full details.

### Quick Install

```bash
# On the GPU server
cd ~/bob-manager/gpu-services
sudo bash install.sh
```

This installs each enabled service as a systemd unit. Ports:

| Service | Port | VRAM |
|---------|------|------|
| MusicGen | 3014 | ~8 GB |
| Bark | 3015 | ~6 GB |
| RVC | 3016 | ~4 GB |
| CoquiTTS | 3017 | ~4 GB |
| STT | 7865 | ~4 GB |
| LTX-Video | 3018 | ~12 GB |
| Wan-Video | 3019 | ~14 GB |

Configure service URLs in the agent environment:

```env
MUSICGEN_URL=http://localhost:3014
BARK_URL=http://localhost:3015
RVC_URL=http://localhost:3016
COQUI_TTS_URL=http://localhost:3017
STT_URL=http://localhost:7865
LTX_VIDEO_URL=http://localhost:3018
WAN_VIDEO_URL=http://localhost:3019
```

---

## 12. Remotion Video Rendering

The Remotion API service enables programmatic video rendering. It runs alongside the control plane.

It is included in the main `docker-compose.yml` as `bob-remotion`:

```yaml
bob-remotion:
  build: ./remotion-api
  ports:
    - "${BIND_ADDR:-0.0.0.0}:3100:3100"
  networks:
    - bob-network
```

No additional configuration is needed — it starts automatically with `docker compose up`.

---

## 13. Related Documents

- [ARCHITECTURE.md](ARCHITECTURE.md) — System architecture
- [CONFIGURATION.md](CONFIGURATION.md) — All environment variables
- [GPU_SERVICES.md](GPU_SERVICES.md) — GPU service details
- [AGENT.md](AGENT.md) — Agent architecture and installation

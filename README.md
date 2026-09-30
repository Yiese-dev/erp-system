# Campus ERP

## VPS Deployment

Target: `root@38.242.246.126`, checkout `/root/erp-system`, public URL
<https://campus--erp.duckdns.org>. These commands assume a fresh **Ubuntu 22.04+
or Debian 12+** server with root access. Use at least 4 GB RAM for the full stack
and allow space for Docker images, PostgreSQL, WAL archives, and backups.

Host Nginx terminates HTTPS and proxies to `127.0.0.1:8080`. The Docker gateway
serves the production React build and routes the four backend APIs. PostgreSQL,
RabbitMQ, workers, and monitoring run in Docker; no host Python or Node setup is
needed. Database volumes, signing keys, and `.env` survive updates.

This remains a **demo application**: seeded synthetic institutions/users, a
simulated mobile-money provider, and Mailpit instead of real outgoing email.
Deploy with synthetic data only. HTTPS does not make these integrations suitable
for real payments or real student/payroll records.

### 1. Publish the Deployment Files and Configure DNS

Commit and push these changes from your development machine before cloning or
updating the VPS. The deployment script pulls the current branch's upstream.

In [DuckDNS](https://www.duckdns.org/), create `campus--erp` (two hyphens) and set
its IPv4 address to `38.242.246.126`. Remove any incorrect IPv6/AAAA record.
Allow inbound TCP **80 and 443** in your VPS provider's firewall. Keep your SSH
port open. Do not expose Docker ports 8080, 8443, 3001, PostgreSQL, or RabbitMQ.

```bash
ssh root@38.242.246.126
```

### 2. Install Docker, Nginx, and Certbot

Run on the VPS. If Docker is already installed, keep the existing installation
and verify that `docker compose version` works rather than replacing it.

```bash
apt-get update
apt-get install -y ca-certificates curl git nginx certbot python3-certbot-nginx openssl jq dnsutils

. /etc/os-release
case "$ID" in ubuntu|debian) ;; *) echo "Ubuntu or Debian required"; exit 1 ;; esac
install -m 0755 -d /etc/apt/keyrings
curl -fsSL "https://download.docker.com/linux/$ID/gpg" -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
printf 'deb [arch=%s signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/%s %s stable\n' \
	"$(dpkg --print-architecture)" "$ID" "$VERSION_CODENAME" > /etc/apt/sources.list.d/docker.list
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker nginx
docker compose version
```

If UFW is already active, allow your actual SSH port before changing firewall
rules, then allow HTTP and HTTPS with `ufw allow 'Nginx Full'`. Do not enable or
reset a firewall blindly over SSH.

### 3. Clone and Deploy

```bash
cd /root
git clone https://github.com/Yiese-dev/erp-system.git
cd /root/erp-system
bash update.sh
```

For a private repository, configure a read-only GitHub deploy key on the VPS and
clone with `git@github.com:Yiese-dev/erp-system.git` instead. Do not put access
tokens in the clone URL, shell history, or repository files.

On first run, `update.sh` creates a mode-600 `.env` with random database, broker,
signature, monitoring, and login secrets. It sets the allowed origin to the HTTPS
domain and retains demo seeding so you have an initial administrator. Existing
`.env` files are preserved, but missing/development secrets or a missing HTTPS
origin cause the script to stop before deployment. Do not reuse the local demo
`.env` on the VPS.

The script checks for concurrent deployments and a clean checkout, fetches a
fast-forward update, pulls dependencies, builds all backend/worker images and
the frontend, reruns idempotent migrations, recreates application containers,
and checks readiness through the gateway. There is a brief restart window; this
is not a zero-downtime or automatic-rollback deployment. Build failures occur
before running applications are restarted. Do not make incompatible schema
changes without a backup and maintenance plan.

### 4. Enable the Domain and HTTPS

Check that DNS resolves to the VPS before requesting a certificate:

```bash
dig +short A campus--erp.duckdns.org
dig +short AAAA campus--erp.duckdns.org
curl -fsS http://127.0.0.1:8080/healthz
install -m 0644 infra/gateway/campus--erp.duckdns.org.conf /etc/nginx/sites-available/campus--erp.duckdns.org
ln -sfn /etc/nginx/sites-available/campus--erp.duckdns.org /etc/nginx/sites-enabled/campus--erp.duckdns.org
nginx -t && systemctl reload nginx
certbot --nginx -d campus--erp.duckdns.org --redirect
systemctl enable --now certbot.timer
certbot renew --dry-run
curl -fsS https://campus--erp.duckdns.org/healthz
```

Supply your email and accept the terms in Certbot's prompts. It adds the HTTPS
listener and HTTP-to-HTTPS redirect to this site. Install the supplied Nginx
site **once**, not after every update: copying it again would remove Certbot's
TLS configuration. The update script does not modify host Nginx or certificates.
The gateway's internal self-signed certificate is not the public certificate.
Sign in over HTTPS; the app's secure cookies intentionally do not work over HTTP.

### 5. First Login

Open <https://campus--erp.duckdns.org> and use:

- Institution: `ictu`
- Email: `superadmin@campus.test`
- Password: the generated `CAMPUS_DEMO_PASSWORD` value in `/root/erp-system/.env`

Read the password privately on the VPS; do not paste it into chat or logs. The
production login page does not show the local demo-password shortcuts. All
seeded users initially share this generated password, so change their passwords
or disable unused accounts before sharing access. Changing
`CAMPUS_DEMO_PASSWORD` after the database has been seeded does **not** reset
existing users. Setting `CAMPUS_DEMO=0` on an empty database creates no initial
administrator; changing it later does not delete the seeded data.

### Future Updates

After pushing your application changes to GitHub, run on the VPS:

```bash
cd /root/erp-system
bash update.sh
```

To deliberately deploy the current local checkout without fetching Git updates:

```bash
bash update.sh --no-pull
```

Do not run `docker compose down -v`, delete volumes, regenerate `.env`, or rotate
database passwords in `.env` without updating the database roles too. Keep an
encrypted off-server copy of `.env`, signing keys, and database backups. The
included daily PostgreSQL backups/WAL archives are on the **same VPS** and do not
protect against losing the server or its disk. Monitor disk space and copy backups
off-server. Never commit `.env` or signing keys to Git.

### Troubleshooting

```bash
cd /root/erp-system
docker compose ps -a
docker compose logs --tail=100 gateway identity academic finance hr
docker compose logs --tail=100 migrate-identity migrate-academic migrate-finance migrate-hr
nginx -t
journalctl -u nginx --no-pager -n 50
curl -fsS http://127.0.0.1:8080/healthz
```

A certificate failure usually means DNS is not pointing at the VPS, port 80 is
blocked, or an incorrect AAAA record routes validation elsewhere. A login-origin
error means `CAMPUS_ORIGINS` does not include the exact HTTPS origin; correct
`.env` and rerun `bash update.sh --no-pull`. Review logs locally and redact secrets
before sharing them.
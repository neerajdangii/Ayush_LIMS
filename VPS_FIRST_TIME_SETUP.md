# VPS First-Time Setup

This guide explains how to deploy this application on a VPS for the first time using the scripts included in this repository.

This setup is intended for:
- internal team testing
- low traffic usage
- no SSL for now
- no Nginx for now

## 1. Prerequisites

You need a Linux VPS with:
- Docker installed
- `docker-compose` or `docker compose` available
- Git installed

## 2. SSH into the VPS

```bash
ssh root@your-vps-ip
```

## 3. Clone the repository

Clone the repository into `/root/Ayush_Project`:

```bash
git clone https://github.com/neerajdangii/Ayush_Project.git /root/Ayush_Project
cd /root/Ayush_Project
```

## 4. Configure `.env.prod`

Open `.env.prod` and update the values for your VPS:

```bash
vim .env.prod
```

Use values like these:

```env
DJANGO_SECRET_KEY=put-a-long-random-secret-here
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=your-vps-ip
# Must exactly match the URL used in the browser (include :8000 for direct Gunicorn).
DJANGO_CSRF_TRUSTED_ORIGINS=http://your-vps-ip:8000
DJANGO_TIME_ZONE=Asia/Kolkata
DJANGO_USE_POSTGRES=True
# False for this direct-Gunicorn setup. Set True only behind a trusted HTTPS proxy.
DJANGO_SECURE_PROXY_SSL_HEADER=False
DJANGO_SECURE_SSL_REDIRECT=False
DJANGO_SESSION_COOKIE_SECURE=False
DJANGO_CSRF_COOKIE_SECURE=False
DJANGO_SECURE_HSTS_SECONDS=0
DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS=False
DJANGO_SECURE_HSTS_PRELOAD=False

DATABASE_URL=

POSTGRES_DB=lims_db
POSTGRES_USER=postgres
POSTGRES_PASSWORD=replace-with-strong-db-password
POSTGRES_HOST=db
POSTGRES_PORT=5432
```

The deployment script copies `.env.prod` into `.env` before running Docker Compose, so keep `.env.prod` updated.

## 5. Make the scripts executable

```bash
chmod +x first_time_deploy.sh update_app.sh
```

## 6. Run the first-time deployment script

```bash
./first_time_deploy.sh
```

## 7. Create the admin user

After the containers are up, create a superuser:

```bash
docker-compose exec web python manage.py createsuperuser
```

If your VPS uses the newer Compose plugin instead, use:

```bash
docker compose exec web python manage.py createsuperuser
```

## 8. Open the application

Open this in your browser:

```text
http://your-vps-ip:8000/accounts/login/
```

Log in using the superuser you created.

## CSRF troubleshooting

Use one canonical browser URL for the application. Do not switch between the
VPS IP address, a hostname, and a domain in the same browser session. Set
`DJANGO_ALLOWED_HOSTS` and `DJANGO_CSRF_TRUSTED_ORIGINS` to that exact public
host/origin, then rebuild the web container. For example:

```env
# Direct Gunicorn
DJANGO_ALLOWED_HOSTS=203.0.113.10
DJANGO_CSRF_TRUSTED_ORIGINS=http://203.0.113.10:8000

# HTTPS domain behind a reverse proxy
DJANGO_ALLOWED_HOSTS=lims.example.com
DJANGO_CSRF_TRUSTED_ORIGINS=https://lims.example.com
DJANGO_SECURE_PROXY_SSL_HEADER=True
DJANGO_SESSION_COOKIE_SECURE=True
DJANGO_CSRF_COOKIE_SECURE=True
```

After changing these settings, delete the site's cookies (or use a private
window) and reload the login page before submitting any form. Keep
`DJANGO_DEBUG=False` on the live server so diagnostic details are not exposed.

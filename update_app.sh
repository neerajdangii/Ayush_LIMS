#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="/root/Ayush_Project"

if command -v docker-compose >/dev/null 2>&1; then
  COMPOSE_CMD="docker-compose"
elif docker compose version >/dev/null 2>&1; then
  COMPOSE_CMD="docker compose"
else
  echo "Error: neither docker-compose nor docker compose is available."
  exit 1
fi

echo "Starting manual application update..."
cd "$PROJECT_DIR"

echo "Current branch:"
git branch --show-current

echo "Current commit before pull:"
git log -1 --oneline

echo "Pulling latest changes..."
git pull

echo "Current commit after pull:"
git log -1 --oneline

echo "Syncing .env with .env.prod for Docker Compose variable substitution..."
cp .env.prod .env

echo "Rebuilding and restarting containers..."
$COMPOSE_CMD up -d --build

echo "Container status:"
$COMPOSE_CMD ps

echo "Django deployment check:"
$COMPOSE_CMD exec -T web python manage.py check --deploy || true

echo "Active CSRF deployment settings:"
$COMPOSE_CMD exec -T web python manage.py shell -c "from django.conf import settings; print('DEBUG=', settings.DEBUG); print('ALLOWED_HOSTS=', settings.ALLOWED_HOSTS); print('CSRF_TRUSTED_ORIGINS=', settings.CSRF_TRUSTED_ORIGINS); print('CSRF_COOKIE_SECURE=', settings.CSRF_COOKIE_SECURE); print('SECURE_PROXY_SSL_HEADER=', settings.SECURE_PROXY_SSL_HEADER)"

echo "TDS migration status:"
$COMPOSE_CMD exec -T web python manage.py showmigrations reports | grep 0009_tdsdocumenttemplate || true

echo "Recent web logs:"
$COMPOSE_CMD logs --tail=100 web

echo "Manual update complete."

#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${GCP_PROJECT:-project-990664b0-1bae-4746-88d}"
PROJECT_NUMBER="221757952819"
BACKUP_BUCKET="project-naturalpath-db-backups"
DATA_DEVICE="/dev/disk/by-id/google-naturepath-data-disk"
DATA_ROOT="/srv/naturepath-data"

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y ca-certificates curl docker.io docker-compose-v2 jq
systemctl enable --now docker

if ! blkid "${DATA_DEVICE}" >/dev/null 2>&1; then
  mkfs.ext4 -F "${DATA_DEVICE}"
fi
mkdir -p "${DATA_ROOT}"
if ! mountpoint -q "${DATA_ROOT}"; then
  mount "${DATA_DEVICE}" "${DATA_ROOT}"
fi
if ! grep -q "${DATA_DEVICE}" /etc/fstab; then
  echo "${DATA_DEVICE} ${DATA_ROOT} ext4 defaults,nofail 0 2" >> /etc/fstab
fi
mkdir -p "${DATA_ROOT}/mongodb" "${DATA_ROOT}/redis" "${DATA_ROOT}/backups" /etc/naturepath
chmod 700 "${DATA_ROOT}/mongodb" "${DATA_ROOT}/redis" "${DATA_ROOT}/backups" /etc/naturepath

metadata_token() {
  curl -fsS -H 'Metadata-Flavor: Google' \
    'http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token' \
    | jq -r '.access_token'
}

secret_value() {
  local secret_name="$1"
  local token
  token="$(metadata_token)"
  curl -fsS -H "Authorization: Bearer ${token}" \
    "https://secretmanager.googleapis.com/v1/projects/${PROJECT_NUMBER}/secrets/${secret_name}/versions/latest:access" \
    | jq -r '.payload.data' | base64 -d
}

MONGO_ROOT_PASSWORD="$(secret_value mongo-root-password)"
MONGO_APP_PASSWORD="$(secret_value mongo-app-password)"
REDIS_PASSWORD="$(secret_value redis-password)"

umask 077
{
  echo "MONGO_ROOT_PASSWORD=${MONGO_ROOT_PASSWORD}"
  echo "MONGO_APP_PASSWORD=${MONGO_APP_PASSWORD}"
  echo "REDIS_PASSWORD=${REDIS_PASSWORD}"
} > /etc/naturepath/.env

cat > /etc/naturepath/compose.yaml <<'YAML'
services:
  mongodb:
    image: mongo:8.0
    container_name: naturepath-mongodb
    restart: unless-stopped
    env_file: .env
    environment:
      MONGO_INITDB_ROOT_USERNAME: root
      MONGO_INITDB_ROOT_PASSWORD: ${MONGO_ROOT_PASSWORD}
    command: ["mongod", "--auth", "--bind_ip_all"]
    ports:
      - "27017:27017"
    volumes:
      - /srv/naturepath-data/mongodb:/data/db
    healthcheck:
      test: ["CMD-SHELL", "mongosh --quiet --username root --password \"$$MONGO_ROOT_PASSWORD\" --authenticationDatabase admin --eval 'db.adminCommand({ ping: 1 })' >/dev/null"]
      interval: 10s
      timeout: 5s
      retries: 20
      start_period: 30s

  redis:
    image: redis:7.4-alpine
    container_name: naturepath-redis
    restart: unless-stopped
    env_file: .env
    command: ["sh", "-c", "exec redis-server --appendonly yes --appendfsync everysec --requirepass \"$$REDIS_PASSWORD\""]
    ports:
      - "6379:6379"
    volumes:
      - /srv/naturepath-data/redis:/data
    healthcheck:
      test: ["CMD-SHELL", "redis-cli -a \"$$REDIS_PASSWORD\" --no-auth-warning ping | grep -q PONG"]
      interval: 10s
      timeout: 5s
      retries: 20
      start_period: 10s
YAML

cd /etc/naturepath
docker compose pull
docker compose up -d

for _ in $(seq 1 30); do
  if docker exec naturepath-mongodb mongosh --quiet \
    --username root --password "${MONGO_ROOT_PASSWORD}" --authenticationDatabase admin \
    --eval 'db.adminCommand({ ping: 1 }).ok' | grep -q 1; then
    break
  fi
  sleep 5
done

docker exec -e APP_PASSWORD="${MONGO_APP_PASSWORD}" naturepath-mongodb \
  mongosh --quiet --username root --password "${MONGO_ROOT_PASSWORD}" \
  --authenticationDatabase admin --eval '
    const appDb = db.getSiblingDB("natural_path");
    if (!appDb.getUser("naturepath")) {
      appDb.createUser({
        user: "naturepath",
        pwd: process.env.APP_PASSWORD,
        roles: [{ role: "dbOwner", db: "natural_path" }]
      });
    }
  '

cat > /usr/local/sbin/naturepath-backup <<'BACKUP'
#!/usr/bin/env bash
set -euo pipefail
umask 077
source /etc/naturepath/.env
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
archive="/srv/naturepath-data/backups/natural-path-${stamp}.archive.gz"
docker exec naturepath-mongodb mongodump --quiet \
  --username root --password "${MONGO_ROOT_PASSWORD}" --authenticationDatabase admin \
  --db natural_path --archive --gzip > "${archive}"
if [[ "$(stat -c '%s' "${archive}")" -lt 1024 ]]; then
  echo "Backup archive is unexpectedly small; refusing upload" >&2
  exit 1
fi
token="$(curl -fsS -H 'Metadata-Flavor: Google' \
  'http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token' \
  | jq -r '.access_token')"
object_name="daily/$(basename "${archive}")"
curl -fsS -X POST -H "Authorization: Bearer ${token}" \
  -H 'Content-Type: application/octet-stream' \
  --data-binary "@${archive}" \
  "https://storage.googleapis.com/upload/storage/v1/b/project-naturalpath-db-backups/o?uploadType=media&name=${object_name}" >/dev/null
find /srv/naturepath-data/backups -type f -name '*.archive.gz' -mtime +7 -delete
BACKUP
chmod 700 /usr/local/sbin/naturepath-backup

cat > /etc/systemd/system/naturepath-backup.service <<'UNIT'
[Unit]
Description=Back up the Natural Path MongoDB database
After=docker.service

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/naturepath-backup
UNIT

cat > /etc/systemd/system/naturepath-backup.timer <<'TIMER'
[Unit]
Description=Daily Natural Path MongoDB backup

[Timer]
OnCalendar=*-*-* 03:15:00 UTC
Persistent=true
RandomizedDelaySec=600

[Install]
WantedBy=timers.target
TIMER

systemctl daemon-reload
systemctl enable --now naturepath-backup.timer
/usr/local/sbin/naturepath-backup

docker ps --format '{{.Names}} {{.Status}}'

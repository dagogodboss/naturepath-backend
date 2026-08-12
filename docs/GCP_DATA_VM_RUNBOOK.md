# GCP data VM operations

Production MongoDB and Redis run on `naturepath-data-1` in `us-central1-a`.
The VM has private IP `10.40.0.10`, no public IP, and is reachable for
administration only through Google IAP. Cloud Run uses Direct VPC egress on
`naturepath-prod/naturepath-app-us-central1`.

## Health checks

```bash
gcloud compute ssh naturepath-data-1 \
  --project project-naturalpath \
  --zone us-central1-a \
  --tunnel-through-iap \
  --command='sudo docker ps; sudo systemctl status naturepath-backup.timer'
```

MongoDB 8.0 persists at `/srv/naturepath-data/mongodb`. Redis 7.4 persists at
`/srv/naturepath-data/redis` with AOF and `appendfsync everysec`. Credentials
and connection URIs are stored in Secret Manager; do not copy them into this
repository.

## Backups

- Daily Mongo archive: 03:15 UTC to `gs://project-naturalpath-db-backups/daily/`.
- Pre-cutover and final Atlas archives: `pre-cutover/` and `cutover/` in the same bucket.
- Daily persistent-disk snapshot policy: `naturepath-data-daily-snapshots`.
- GCS object versioning is enabled.

Run an archive backup immediately:

```bash
gcloud compute ssh naturepath-data-1 \
  --project project-naturalpath \
  --zone us-central1-a \
  --tunnel-through-iap \
  --command='sudo /usr/local/sbin/naturepath-backup'
```

## Rollback

Atlas and Upstash secrets remain as `mongo-url` and `redis-url`. VM connection
secrets are `mongo-url-vm` and `redis-url-vm`.

To roll the API back immediately, route traffic to the last Atlas revision:

```bash
gcloud run services update-traffic natural-path-api \
  --project project-naturalpath \
  --region us-central1 \
  --to-revisions natural-path-api-00010-nmv=100
```

For a longer rollback, set `MONGO_SECRET_NAME=mongo-url` and
`REDIS_SECRET_NAME=redis-url` in the local deploy configuration and redeploy
the API and worker. Restore writes made after cutover from the latest VM archive
before permanently reverting the database.

## Provisioning source

The idempotent VM bootstrap is maintained outside the backend repository at
`deploy/gcp/07-bootstrap-data-vm.sh` in the NaturePath workspace. Update the VM
startup-script metadata whenever that file changes.

# n8n Deployment

This directory runs n8n as an isolated Docker Compose stack with a dedicated
PostgreSQL database and persistent Docker volumes.

```bash
cd deploy/n8n
./bootstrap-env.sh
docker compose up -d
```

Default URL:

```text
http://192.168.1.100:5678
```

Useful commands:

```bash
docker compose ps
docker compose logs -f n8n
docker compose pull
docker compose up -d
docker compose down
```

The generated `.env` contains `POSTGRES_PASSWORD` and `N8N_ENCRYPTION_KEY` and
is intentionally not tracked. Keep `N8N_ENCRYPTION_KEY` stable; changing it can
make saved credentials unreadable.

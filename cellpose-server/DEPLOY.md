[**English**](DEPLOY.md) | [简体中文](DEPLOY.zh-CN.md)

# Cellpose Server Deployment

## 1. Prepare configuration

This directory does not contain real credentials. Copy the template once:

```powershell
Copy-Item .env.example .env
```

Linux/macOS:

```bash
cp .env.example .env
```

Edit only `.env` afterward. At minimum, review `CELLPOSE_API_KEY`, model, device, bind address, and port. Never commit or distribute an `.env` containing a real key.

## 2. Start the GPU service

The host needs Docker Engine, Docker Compose, an NVIDIA driver, and NVIDIA Container Toolkit.

```bash
docker compose --env-file .env up --build -d
docker compose --env-file .env logs -f cellpose
```

The container starts `app:app` directly through Uvicorn; there is no separate `start.py`. On first startup, the configured `CELLPOSE_MODEL` may be downloaded and stored in the `cellpose-models` Docker volume, so readiness may take longer.

## 3. Check status

```bash
docker compose --env-file .env ps
docker compose --env-file .env exec cellpose python healthcheck.py
```

After the health check passes, clients call `/v1/segment` through the host port configured in `.env`.

## 4. Stop or remove the service

```bash
docker compose --env-file .env stop
docker compose --env-file .env start
docker compose --env-file .env down
```

`down` preserves the model volume by default. Do not add `-v` unless the model cache should also be removed.

## 5. API

- `GET /healthz` returns service state, version, model, and inference device.
- `POST /v1/segment` accepts `multipart/form-data`; the image field is `file`, and parameter defaults come from `.env`.
- When `CELLPOSE_API_KEY` is configured, requests must provide the same value in `X-API-Key`.
- A successful ZIP response contains `mask.tif`, `metadata.json`, `instances.csv`, and normally `overlay.png`.
- FastAPI documentation is available at `/docs`.

## 6. Security boundary

The default bind configuration is intended for local access. For remote use, place the service behind a protected private network or TLS-enabled reverse proxy and use a strong API key. Do not expose an unencrypted, unauthenticated inference port directly to the internet.

One container executes one inference request at a time to reduce GPU-memory contention. The Compose file targets NVIDIA GPUs; a CPU deployment must remove the GPU-device reservation and select a CPU device in `.env`.

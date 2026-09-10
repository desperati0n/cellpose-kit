[**English**](service-connection.md) | [简体中文](service-connection.zh-CN.md)

# Service connection

This Skill is a client for an independently deployed Cellpose-SAM HTTP service. It does not install, start, or configure the model server.

## Client configuration

Copy `.env.example` to `.env` once, then edit only `.env`. The client reads these connection values from it:

| Variable | Purpose |
|---|---|
| `CELLPOSE_SERVICE_URL` | Base URL of the existing service |
| `CELLPOSE_API_KEY` | Value sent in `X-API-Key` when authentication is enabled |
| `CELLPOSE_TIMEOUT_SECONDS` | End-to-end request timeout |

The same file also contains the persistent segmentation defaults. Process environment variables can override the file in managed deployments. Keep `.env` out of distribution and version control, and keep the API key out of prompts, command-line arguments, logs, and generated files.

## Expected HTTP contract

The client sends `POST /v1/segment` as `multipart/form-data` with the image in the `file` field and optional segmentation parameters. A successful response must be an `application/zip` archive containing `mask.tif`, `metadata.json`, and `instances.csv`; it normally also contains `overlay.png`.

The bundled client accepts PNG, JPEG, BMP, TIF, and TIFF input. If the service is unreachable or returns an error, report the configured URL and concise failure without exposing credentials. Do not silently fall back to another model.

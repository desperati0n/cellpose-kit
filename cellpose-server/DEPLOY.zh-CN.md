[English](DEPLOY.md) | **简体中文**

# Cellpose Server 部署说明

## 1. 准备配置

本目录不携带真实密钥。首次部署时复制配置模板：

```powershell
Copy-Item .env.example .env
```

Linux：

```bash
cp .env.example .env
```

此后只编辑 `.env`。至少检查 `CELLPOSE_API_KEY`、模型、设备、监听地址和端口；不要把含真实密钥的 `.env` 提交或交付给其他人。

## 2. 启动 GPU 服务

服务器需要 Docker Engine、Docker Compose、NVIDIA 驱动和 NVIDIA Container Toolkit。

```bash
docker compose --env-file .env up --build -d
docker compose --env-file .env logs -f cellpose
```

容器直接通过 Uvicorn 启动 `app:app`，没有额外的 `start.py`。第一次启动会下载 `.env` 中 `CELLPOSE_MODEL` 指定的模型，并保存到 `cellpose-models` Docker Volume，因此就绪时间较长。

## 3. 检查状态

```bash
docker compose --env-file .env ps
docker compose --env-file .env exec cellpose python healthcheck.py
```

健康检查成功后，调用端使用 `.env` 中配置的主机端口访问 `/v1/segment`。

## 4. 停止服务

```bash
docker compose --env-file .env stop
docker compose --env-file .env start
docker compose --env-file .env down
```

`down` 默认保留模型 Volume。除非确实要重新下载模型，否则不要执行带 `-v` 的 `down`。

## 5. API

- `GET /healthz`：返回服务状态、版本、模型和推理设备。
- `POST /v1/segment`：接收 `multipart/form-data`，图像字段名为 `file`；分割参数的默认值统一来自 `.env`。
- 配置了 `CELLPOSE_API_KEY` 时，请求必须携带同值的 `X-API-Key`。
- 成功响应为 ZIP，包含 `mask.tif`、`metadata.json`、`instances.csv`，通常还包含 `overlay.png`。
- FastAPI 自动接口文档位于 `/docs`。

## 6. 安全边界

默认绑定设置仅允许本机访问。需要远程调用时，通过受保护的内网或带 TLS 的反向代理开放，并设置强 API Key；不要直接把未加密、未认证的推理端口暴露到公网。

每个容器一次只执行一个推理任务，以降低 GPU 显存竞争。当前 Compose 配置面向 NVIDIA GPU；CPU 部署需要移除 GPU 设备预留，并在 `.env` 中选择 CPU 设备。

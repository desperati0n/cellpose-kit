[English](service-connection.md) | **简体中文**

# 服务连接说明

这个 Skill 是独立部署的 Cellpose-SAM HTTP 服务的调用端，不负责安装、启动或配置模型服务。

## 调用端配置

首次使用时将 `.env.example` 复制为 `.env`，之后只编辑 `.env`。调用端从中读取：

| 变量 | 用途 |
|---|---|
| `CELLPOSE_SERVICE_URL` | 已部署服务的基础 URL |
| `CELLPOSE_API_KEY` | 启用鉴权时通过 `X-API-Key` 发送的值 |
| `CELLPOSE_TIMEOUT_SECONDS` | 端到端请求超时时间 |

同一文件还保存长期使用的默认分割参数。托管部署可以通过进程环境变量覆盖文件值。不要分发或提交 `.env`，也不要在提示词、命令行参数、日志或生成文件中泄露 API Key。

## 预期 HTTP 契约

调用端以 `multipart/form-data` 向 `POST /v1/segment` 发送请求，图片字段名为 `file`，并可附带分割参数。成功响应必须是 `application/zip`，其中包含 `mask.tif`、`metadata.json` 和 `instances.csv`，通常还包含 `overlay.png`。

客户端接受 PNG、JPEG、BMP、TIF 和 TIFF。如果服务无法访问或返回错误，应报告已配置 URL 和简要失败原因，但不能暴露凭据，也不能静默切换到其他模型。

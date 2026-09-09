from __future__ import annotations

import asyncio
import csv
import hashlib
import json
import os
import secrets
import sys
import tempfile
import time
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import numpy as np
import tifffile
import torch
from cellpose import io as cellpose_io
from cellpose import models
from cellpose import utils as cellpose_utils
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile, status
from fastapi.background import BackgroundTasks
from fastapi.responses import FileResponse
from PIL import Image


CONFIG_MODULE_DIR = Path(__file__).resolve().parent
if not (CONFIG_MODULE_DIR / "cellpose_config.py").is_file():
    CONFIG_MODULE_DIR = CONFIG_MODULE_DIR.parent
if str(CONFIG_MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(CONFIG_MODULE_DIR))

from cellpose_config import config_bool, config_optional_float, load_config


SERVICE_VERSION = "1.0.0"
ALLOWED_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}
SERVICE_CONFIG = load_config(
    (
        "CELLPOSE_MODEL",
        "CELLPOSE_DEVICE",
        "CELLPOSE_API_KEY",
        "CELLPOSE_MAX_UPLOAD_MB",
        "CELLPOSE_CELLPROB_THRESHOLD",
        "CELLPOSE_FLOW_THRESHOLD",
        "CELLPOSE_MIN_SIZE",
        "CELLPOSE_DIAMETER",
        "CELLPOSE_NORMALIZE",
        "CELLPOSE_INVERT",
    )
)
MODEL_NAME = SERVICE_CONFIG["CELLPOSE_MODEL"]
DEVICE_SETTING = SERVICE_CONFIG["CELLPOSE_DEVICE"].strip().lower()
API_KEY = SERVICE_CONFIG["CELLPOSE_API_KEY"]
MAX_UPLOAD_BYTES = int(SERVICE_CONFIG["CELLPOSE_MAX_UPLOAD_MB"]) * 1024 * 1024
DEFAULT_CELLPROB_THRESHOLD = float(SERVICE_CONFIG["CELLPOSE_CELLPROB_THRESHOLD"])
DEFAULT_FLOW_THRESHOLD = float(SERVICE_CONFIG["CELLPOSE_FLOW_THRESHOLD"])
DEFAULT_MIN_SIZE = int(SERVICE_CONFIG["CELLPOSE_MIN_SIZE"])
DEFAULT_DIAMETER = config_optional_float(SERVICE_CONFIG, "CELLPOSE_DIAMETER")
DEFAULT_NORMALIZE = config_bool(SERVICE_CONFIG, "CELLPOSE_NORMALIZE")
DEFAULT_INVERT = config_bool(SERVICE_CONFIG, "CELLPOSE_INVERT")

model: models.CellposeModel | None = None
model_device = "uninitialized"
inference_lock = asyncio.Lock()


def _resolve_device() -> torch.device:
    """根据环境变量与 CUDA 可用性选择 Cellpose 推理设备。"""
    if DEVICE_SETTING == "auto":
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")
    device = torch.device(DEVICE_SETTING)
    if device.type == "cuda" and not torch.cuda.is_available():
        raise RuntimeError(f"CELLPOSE_DEVICE={DEVICE_SETTING!r}, but CUDA is unavailable")
    return device


@asynccontextmanager
async def lifespan(_: FastAPI):
    """在服务启动时加载一次模型，并在服务关闭时释放全局引用。"""
    global model, model_device
    device = _resolve_device()
    model = models.CellposeModel(
        pretrained_model=MODEL_NAME,
        device=device,
        use_bfloat16=device.type == "cuda",
    )
    model_device = str(device)
    yield
    model = None


app = FastAPI(
    title="Cellpose-SAM Segmentation Service",
    version=SERVICE_VERSION,
    lifespan=lifespan,
)


def _authorize(x_api_key: str | None = Header(default=None)) -> None:
    """在服务配置了 API Key 时校验请求头中的访问密钥。"""
    if API_KEY and (x_api_key is None or not secrets.compare_digest(API_KEY, x_api_key)):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing API key")


def _instance_count(mask: np.ndarray) -> int:
    """统计标签掩膜中除背景零值之外的实例数量。"""
    labels = np.unique(mask)
    return int(labels.size - int(labels.size > 0 and labels[0] == 0))


def _to_rgb8(image: np.ndarray) -> np.ndarray | None:
    """把支持的灰度或多通道图像归一化为可预览的八位 RGB 图像。"""
    image = np.asarray(image).squeeze()
    if image.ndim == 2:
        image = np.repeat(image[..., None], 3, axis=2)
    elif image.ndim == 3 and image.shape[-1] in {1, 3, 4}:
        image = image[..., :3]
        if image.shape[-1] == 1:
            image = np.repeat(image, 3, axis=2)
    elif image.ndim == 3 and image.shape[0] in {1, 3, 4}:
        image = np.moveaxis(image[:3], 0, -1)
        if image.shape[-1] == 1:
            image = np.repeat(image, 3, axis=2)
    else:
        return None
    if image.dtype == np.uint8:
        return image.copy()
    values = image.astype(np.float32)
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return np.zeros(values.shape, dtype=np.uint8)
    low, high = np.percentile(finite, (1, 99))
    if high <= low:
        high = low + 1.0
    return np.clip((values - low) * (255.0 / (high - low)), 0, 255).astype(np.uint8)


def _write_overlay(image: np.ndarray, mask: np.ndarray, path: Path) -> bool:
    """将实例标签着色并叠加到原图上生成可视化预览。"""
    if mask.ndim != 2:
        return False
    rgb = _to_rgb8(image)
    if rgb is None or rgb.shape[:2] != mask.shape:
        return False
    labels = mask.astype(np.uint64)
    colors = np.stack(
        ((labels * 37 + 53) % 256, (labels * 73 + 97) % 256, (labels * 109 + 193) % 256),
        axis=-1,
    ).astype(np.uint8)
    foreground = labels > 0
    blended = rgb.copy()
    blended[foreground] = (
        0.65 * rgb[foreground].astype(np.float32) + 0.35 * colors[foreground].astype(np.float32)
    ).astype(np.uint8)
    outlines = cellpose_utils.masks_to_outlines(mask)
    blended[outlines] = np.array([255, 255, 255], dtype=np.uint8)
    Image.fromarray(blended, mode="RGB").save(path, format="PNG", optimize=True)
    return True


def _write_instances_csv(mask: np.ndarray, path: Path) -> None:
    """把每个非背景实例的标签和像素面积写入 CSV 文件。"""
    labels, counts = np.unique(mask, return_counts=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["label", "area_px"])
        for label, count in zip(labels, counts, strict=True):
            if label:
                writer.writerow([int(label), int(count)])


def _run_inference(
    input_path: Path,
    original_filename: str,
    input_sha256: str,
    cellprob_threshold: float,
    flow_threshold: float,
    min_size: int,
    diameter: float | None,
    normalize: bool,
    invert: bool,
) -> tuple[Path, dict[str, Any]]:
    """运行一次 Cellpose 推理并把掩膜、预览及元数据打包为 ZIP。"""
    if model is None:
        raise RuntimeError("Model is not initialized")
    image = np.asarray(cellpose_io.imread(str(input_path)))
    if image.ndim not in {2, 3}:
        raise ValueError(f"Expected a 2D image or a 2D image with channels; decoded shape is {image.shape}")
    if image.size == 0:
        raise ValueError("Decoded image is empty")

    started = time.perf_counter()
    result = model.eval(
        image,
        diameter=diameter,
        cellprob_threshold=cellprob_threshold,
        flow_threshold=flow_threshold,
        min_size=min_size,
        normalize={"normalize": normalize, "invert": invert},
    )
    inference_ms = round((time.perf_counter() - started) * 1000, 2)
    mask = np.asarray(result[0], dtype=np.uint32)
    if mask.ndim not in {2, 3}:
        raise RuntimeError(f"Unexpected mask shape from Cellpose: {mask.shape}")

    bundle_dir = Path(tempfile.mkdtemp(prefix="cellpose-output-"))
    mask_path = bundle_dir / "mask.tif"
    overlay_path = bundle_dir / "overlay.png"
    instances_path = bundle_dir / "instances.csv"
    metadata_path = bundle_dir / "metadata.json"
    tifffile.imwrite(mask_path, mask, photometric="minisblack")
    overlay_created = _write_overlay(image, mask, overlay_path)
    _write_instances_csv(mask, instances_path)

    metadata: dict[str, Any] = {
        "service_version": SERVICE_VERSION,
        "model": MODEL_NAME,
        "device": model_device,
        "original_filename": original_filename,
        "input_sha256": input_sha256,
        "input_shape": list(image.shape),
        "input_dtype": str(image.dtype),
        "mask_shape": list(mask.shape),
        "mask_dtype": str(mask.dtype),
        "instance_count": _instance_count(mask),
        "inference_ms": inference_ms,
        "overlay_created": overlay_created,
        "parameters": {
            "cellprob_threshold": cellprob_threshold,
            "flow_threshold": flow_threshold,
            "min_size": min_size,
            "diameter": diameter,
            "normalize": normalize,
            "invert": invert,
        },
    }
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    descriptor, zip_name = tempfile.mkstemp(prefix="cellpose-result-", suffix=".zip")
    os.close(descriptor)
    zip_path = Path(zip_name)
    try:
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for artifact in (mask_path, instances_path, metadata_path):
                archive.write(artifact, arcname=artifact.name)
            if overlay_created:
                archive.write(overlay_path, arcname=overlay_path.name)
    except Exception:
        zip_path.unlink(missing_ok=True)
        raise
    finally:
        for artifact in bundle_dir.iterdir():
            artifact.unlink(missing_ok=True)
        bundle_dir.rmdir()
    return zip_path, metadata


async def _save_upload(upload: UploadFile, destination: Path) -> str:
    """流式保存上传文件、限制大小并同时计算其 SHA-256 摘要。"""
    digest = hashlib.sha256()
    size = 0
    with destination.open("wb") as target:
        while chunk := await upload.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Upload is too large")
            digest.update(chunk)
            target.write(chunk)
    if size == 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty")
    return digest.hexdigest()


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    """返回模型加载状态、服务版本、模型名称和当前推理设备。"""
    return {
        "status": "ok" if model is not None else "starting",
        "service_version": SERVICE_VERSION,
        "model": MODEL_NAME,
        "device": model_device,
    }


@app.post("/v1/segment", dependencies=[Depends(_authorize)], response_class=FileResponse)
async def segment(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    cellprob_threshold: float = Form(DEFAULT_CELLPROB_THRESHOLD),
    flow_threshold: float = Form(DEFAULT_FLOW_THRESHOLD),
    min_size: int = Form(DEFAULT_MIN_SIZE),
    diameter: float | None = Form(DEFAULT_DIAMETER),
    normalize: bool = Form(DEFAULT_NORMALIZE),
    invert: bool = Form(DEFAULT_INVERT),
) -> FileResponse:
    """校验分割请求、串行执行推理并返回包含结果文件的 ZIP 响应。"""
    filename = Path(file.filename or "upload.tif").name
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=f"Unsupported image extension: {suffix}")
    if min_size < 0:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="min_size must be zero or greater")
    if diameter is not None and diameter <= 0:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="diameter must be greater than zero")

    with tempfile.TemporaryDirectory(prefix="cellpose-upload-") as temp_dir:
        input_path = Path(temp_dir) / f"input{suffix}"
        try:
            input_sha256 = await _save_upload(file, input_path)
            async with inference_lock:
                zip_path, metadata = await asyncio.to_thread(
                    _run_inference,
                    input_path,
                    filename,
                    input_sha256,
                    cellprob_threshold,
                    flow_threshold,
                    min_size,
                    diameter,
                    normalize,
                    invert,
                )
        except HTTPException:
            raise
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Segmentation failed: {exc}") from exc
        finally:
            await file.close()

    background_tasks.add_task(zip_path.unlink, missing_ok=True)
    response = FileResponse(
        path=zip_path,
        media_type="application/zip",
        filename=f"{Path(filename).stem}_cellpose.zip",
        background=background_tasks,
    )
    response.headers["X-Cellpose-Model"] = MODEL_NAME
    response.headers["X-Instance-Count"] = str(metadata["instance_count"])
    return response

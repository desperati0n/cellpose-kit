#!/usr/bin/env python3
"""Upload one microscopy image to the Cellpose service and extract its results."""

from __future__ import annotations

import argparse
import http.client
import json
import mimetypes
import secrets
import shutil
import ssl
import sys
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import urlsplit


SKILL_ROOT = Path(__file__).resolve().parents[1]
if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))

from cellpose_config import config_bool, config_optional_float, load_config


CHUNK_SIZE = 1024 * 1024
CLIENT_CONFIG = load_config(
    (
        "CELLPOSE_SERVICE_URL",
        "CELLPOSE_API_KEY",
        "CELLPOSE_TIMEOUT_SECONDS",
        "CELLPOSE_CELLPROB_THRESHOLD",
        "CELLPOSE_FLOW_THRESHOLD",
        "CELLPOSE_MIN_SIZE",
        "CELLPOSE_DIAMETER",
        "CELLPOSE_NORMALIZE",
        "CELLPOSE_INVERT",
    )
)


def _field_part(boundary: str, name: str, value: object) -> bytes:
    rendered = str(value).lower() if isinstance(value, bool) else str(value)
    return (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
        f"{rendered}\r\n"
    ).encode("utf-8")


def _safe_extract(archive: Path, destination: Path) -> None:
    destination = destination.resolve()
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.infolist():
            target = (destination / member.filename).resolve()
            if destination != target and destination not in target.parents:
                raise ValueError(f"Unsafe archive member: {member.filename}")
        bundle.extractall(destination)


def _post_image(
    endpoint: str,
    image_path: Path,
    fields: dict[str, object],
    api_key: str | None,
    timeout: float,
    output_zip: Path,
) -> dict[str, str]:
    parsed = urlsplit(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"Invalid service URL: {endpoint}")

    boundary = f"----cellpose-{secrets.token_hex(16)}"
    field_parts = [_field_part(boundary, key, value) for key, value in fields.items()]
    filename = image_path.name.replace('"', "_")
    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    file_header = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: {content_type}\r\n\r\n"
    ).encode("utf-8")
    closing = f"\r\n--{boundary}--\r\n".encode("ascii")
    content_length = (
        sum(len(part) for part in field_parts)
        + len(file_header)
        + image_path.stat().st_size
        + len(closing)
    )

    connection_cls = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
    connection_kwargs: dict[str, object] = {"timeout": timeout}
    if parsed.scheme == "https":
        connection_kwargs["context"] = ssl.create_default_context()
    connection = connection_cls(parsed.hostname, parsed.port, **connection_kwargs)
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"

    try:
        connection.putrequest("POST", path)
        connection.putheader("Content-Type", f"multipart/form-data; boundary={boundary}")
        connection.putheader("Content-Length", str(content_length))
        connection.putheader("Accept", "application/zip")
        if api_key:
            connection.putheader("X-API-Key", api_key)
        connection.endheaders()
        for part in field_parts:
            connection.send(part)
        connection.send(file_header)
        with image_path.open("rb") as source:
            while chunk := source.read(CHUNK_SIZE):
                connection.send(chunk)
        connection.send(closing)

        response = connection.getresponse()
        headers = {key.lower(): value for key, value in response.getheaders()}
        if response.status != 200:
            body = response.read(64 * 1024).decode("utf-8", errors="replace")
            raise RuntimeError(f"Service returned HTTP {response.status}: {body}")
        with output_zip.open("wb") as target:
            while chunk := response.read(CHUNK_SIZE):
                target.write(chunk)
        return headers
    finally:
        connection.close()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path, help="PNG, JPEG, BMP, TIF, or TIFF microscopy image")
    parser.add_argument("--output", type=Path, help="Result directory (default: beside the input image)")
    parser.add_argument(
        "--cellprob-threshold",
        type=float,
        default=float(CLIENT_CONFIG["CELLPOSE_CELLPROB_THRESHOLD"]),
    )
    parser.add_argument(
        "--flow-threshold",
        type=float,
        default=float(CLIENT_CONFIG["CELLPOSE_FLOW_THRESHOLD"]),
    )
    parser.add_argument("--min-size", type=int, default=int(CLIENT_CONFIG["CELLPOSE_MIN_SIZE"]))
    parser.add_argument(
        "--diameter",
        type=float,
        default=config_optional_float(CLIENT_CONFIG, "CELLPOSE_DIAMETER"),
    )
    parser.add_argument(
        "--normalize",
        action=argparse.BooleanOptionalAction,
        default=config_bool(CLIENT_CONFIG, "CELLPOSE_NORMALIZE"),
    )
    parser.add_argument(
        "--invert",
        action=argparse.BooleanOptionalAction,
        default=config_bool(CLIENT_CONFIG, "CELLPOSE_INVERT"),
    )
    parser.add_argument("--timeout", type=float, default=float(CLIENT_CONFIG["CELLPOSE_TIMEOUT_SECONDS"]))
    parser.add_argument("--keep-zip", action="store_true", help="Keep result.zip after extraction")
    parser.add_argument("--force", action="store_true", help="Allow existing files in the output directory to be replaced")
    return parser


def main() -> int:
    args = _parser().parse_args()
    image_path = args.image.expanduser().resolve()
    if not image_path.is_file():
        raise SystemExit(f"Image does not exist: {image_path}")
    if image_path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}:
        raise SystemExit(f"Unsupported image extension: {image_path.suffix}")
    if args.min_size < 0:
        raise SystemExit("--min-size must be zero or greater")

    output_dir = (args.output or image_path.with_name(f"{image_path.stem}_cellpose")).expanduser().resolve()
    if output_dir.exists() and any(output_dir.iterdir()) and not args.force:
        raise SystemExit(f"Output directory is not empty: {output_dir} (use --force to replace result files)")
    output_dir.mkdir(parents=True, exist_ok=True)
    service_url = CLIENT_CONFIG["CELLPOSE_SERVICE_URL"].rstrip("/")
    endpoint = f"{service_url}/v1/segment"
    fields: dict[str, object] = {
        "cellprob_threshold": args.cellprob_threshold,
        "flow_threshold": args.flow_threshold,
        "min_size": args.min_size,
        "invert": args.invert,
        "normalize": args.normalize,
    }
    if args.diameter is not None:
        fields["diameter"] = args.diameter

    temporary = tempfile.NamedTemporaryFile(prefix="cellpose-result-", suffix=".zip", delete=False)
    archive = Path(temporary.name)
    temporary.close()
    try:
        headers = _post_image(
            endpoint=endpoint,
            image_path=image_path,
            fields=fields,
            api_key=CLIENT_CONFIG["CELLPOSE_API_KEY"] or None,
            timeout=args.timeout,
            output_zip=archive,
        )
        _safe_extract(archive, output_dir)
        if args.keep_zip:
            shutil.copy2(archive, output_dir / "result.zip")
        metadata_path = output_dir / "metadata.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {}
        summary = {
            "output_directory": str(output_dir),
            "model": metadata.get("model", headers.get("x-cellpose-model")),
            "instance_count": metadata.get("instance_count", headers.get("x-instance-count")),
            "inference_ms": metadata.get("inference_ms"),
            "files": sorted(item.name for item in output_dir.iterdir() if item.is_file()),
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    except (OSError, RuntimeError, ValueError, zipfile.BadZipFile) as exc:
        print(f"Cellpose request failed ({endpoint}): {exc}", file=sys.stderr)
        return 1
    finally:
        archive.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())

---
name: cellpose-segmentation
description: Segment 2D microscopy images into labeled cell instances by calling a configured Cellpose-SAM HTTP service. Use when an agent needs masks, cell counts, or segmentation previews from local PNG, JPEG, BMP, or TIFF images; do not use for general-purpose image recognition or semantic description.
---

# Cellpose Segmentation

[中文参考](SKILL.zh-CN.md)

Resolve bundled paths relative to this `SKILL.md`. Send each local microscopy image to the service with the bundled client:

```bash
python <skill-directory>/scripts/segment.py INPUT_IMAGE --output OUTPUT_DIRECTORY
```

Read all persistent client settings from `.env` beside this `SKILL.md`; `.env.example` is only the distributable template. The client loads the service URL, API key, timeout, and segmentation defaults from that one file, while process environment variables may override them for managed deployments. Never put a real API key in `SKILL.md`, `.env.example`, a command-line argument, logs, or generated output.

## Interpret every output

The client extracts the service response into the output directory. Interpret the artifacts as follows:

- `mask.tif` is the quantitative segmentation result. It is a `uint32` label raster aligned with the input image's spatial coordinates: `0` means background, and pixels sharing the same positive integer belong to one predicted instance. Positive values are arbitrary per-image identifiers, not biological classes, confidence scores, rankings, or stable IDs across runs. Count unique nonzero labels to obtain the instance count.
- `overlay.png` is an 8-bit RGB visual-QA image. The service normalizes the source image for display, blends each instance with a deterministic pseudo-color, and draws its outline in white. Colors carry no class, confidence, or measurement meaning; never measure intensity or area from this file. It may be absent when the input cannot be represented as a compatible 2D preview, and `metadata.json` records whether it was created.
- `instances.csv` is the per-instance measurement table. Each non-background label has one row: `label` matches the integer stored in `mask.tif`, and `area_px` is the number of pixels assigned to it. `area_px` is not a physical area; convert it using image pixel-size calibration when micrometre-based measurements are required. The row count should equal `metadata.json`'s `instance_count`.
- `metadata.json` is the authoritative run record. `service_version`, `model`, and `device` identify the runtime; `original_filename` and `input_sha256` identify the input; `input_shape`/`input_dtype` and `mask_shape`/`mask_dtype` describe the arrays; `instance_count` is the number of unique nonzero labels; `inference_ms` is server-side model execution time and excludes network transfer; `overlay_created` states whether `overlay.png` exists; and `parameters` contains the exact segmentation settings used for reproducibility.
- `result.zip` appears only with `--keep-zip`; it is a retained copy of the downloaded response archive and does not contain an additional prediction beyond the extracted files.
- The client's standard-output JSON is only a convenience summary containing the output directory, model, instance count, inference time, and extracted filenames. Use the extracted `metadata.json` and artifacts as the authoritative results.

Report the instance count, the exact model and parameters, and any failed consistency check. Link `mask.tif` and `overlay.png` when useful. Treat all results as automated predictions rather than ground truth, visually inspect the overlay before scientific claims, and do not infer cell type, confidence, physical size, or biological identity unless separate calibrated data supports it.

Use the values in `.env` unless the user requests a one-run override or the preview shows a concrete failure. Adjust `--cellprob-threshold` to trade recall against false positives, `--flow-threshold` to change mask quality filtering, and `--min-size` to discard tiny instances. Make persistent changes only in `.env`, not in the script or Skill instructions, and preserve the exact parameters recorded in `metadata.json` when comparing runs.

If the service is unavailable, report the failed URL and concise error. Do not silently substitute another segmentation model, deploy a model, or reconfigure the server. When connection, authentication, or API details are needed, read [references/service-connection.md](references/service-connection.md).

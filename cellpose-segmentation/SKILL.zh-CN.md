# Cellpose Segmentation Skill（中文参考）

[English executable instructions](SKILL.md) | **简体中文参考**

> Agent 实际读取的入口仍是 `SKILL.md`；本文件用于中文阅读，不应替换主文件。

本 Skill 通过已经配置的 Cellpose-SAM HTTP 服务，把二维显微图像分割为带整数标签的细胞实例。适用于需要掩膜、细胞数量或分割预览的本地 PNG、JPEG、BMP、TIF/TIFF 图片，不适用于通用识图或语义描述。

从 `SKILL.md` 所在目录解析脚本路径，并调用：

```bash
python <skill-directory>/scripts/segment.py INPUT_IMAGE --output OUTPUT_DIRECTORY
```

长期配置从同目录 `.env` 读取；`.env.example` 只是可分发模板。调用端从 `.env` 加载服务 URL、API Key、超时和默认分割参数，托管环境可以用进程环境变量覆盖。不要把真实 API Key 放入 `SKILL.md`、`.env.example`、命令行、日志或生成结果。

## 输出解释

- `mask.tif`：定量实例标签，类型为 `uint32`。`0` 是背景，相同正整数属于同一实例。标签只在当前图片内有效，不代表类别、置信度、排名或跨任务稳定 ID。
- `overlay.png`：8 位 RGB 质检预览。颜色和白色边界只用于查看，不能用于测量面积或原始荧光强度。无法生成兼容二维预览时可能缺失，具体见 `metadata.json`。
- `instances.csv`：每个非背景标签一行；`label` 对应 `mask.tif`，`area_px` 是像素面积。换算物理单位必须使用像素尺寸元数据。
- `metadata.json`：权威运行记录，包括版本、模型、设备、输入哈希、图像/掩膜形状、实例数、推理耗时、实际参数和预览生成状态。

调用完成后，应解释每个输出，报告模型、实例数、实际参数及任何一致性异常。`overlay.png` 只能用于质检；不能把预测标注为人工真值，也不能从标签颜色推断生物类别或置信度。

默认使用 `.env` 中的参数。只有在当前任务需要或质检显示明确问题时，才临时调整 `cellprob_threshold`、`flow_threshold`、`min_size` 或 `diameter`。需要长期修改时编辑 `.env`，不要改脚本；比较结果时必须保留 `metadata.json` 中的实际参数。

如果服务不可访问，应报告配置的 URL 和简要错误，不得暴露凭据、静默回退到其他模型或自行启动/配置服务器。连接细节见 [`references/service-connection.zh-CN.md`](references/service-connection.zh-CN.md)。

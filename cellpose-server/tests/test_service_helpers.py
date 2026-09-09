from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import numpy as np

import app


class FakeModel:
    def eval(self, image: np.ndarray, **kwargs: object):
        mask = np.zeros(image.shape[:2], dtype=np.uint32)
        mask[1:3, 1:3] = 1
        mask[3:5, 3:5] = 7
        return mask, [], np.zeros(256, dtype=np.float32)


class ServiceHelperTests(unittest.TestCase):
    def test_instance_count_handles_non_contiguous_labels(self):
        mask = np.array([[0, 1], [7, 7]], dtype=np.uint32)
        self.assertEqual(app._instance_count(mask), 2)

    def test_inference_bundle_contract(self):
        image = np.arange(36, dtype=np.uint16).reshape(6, 6)
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "input.tif"
            input_path.touch()
            with patch.object(app, "model", FakeModel()), patch.object(
                app.cellpose_io, "imread", return_value=image
            ), patch.object(app, "model_device", "cpu"):
                bundle, metadata = app._run_inference(
                    input_path=input_path,
                    original_filename="sample.tif",
                    input_sha256="abc123",
                    cellprob_threshold=0.0,
                    flow_threshold=0.4,
                    min_size=15,
                    diameter=None,
                    normalize=True,
                    invert=False,
                )
            try:
                self.assertEqual(metadata["model"], "cpsam_v2")
                self.assertEqual(metadata["instance_count"], 2)
                with zipfile.ZipFile(bundle) as archive:
                    self.assertEqual(
                        set(archive.namelist()),
                        {"mask.tif", "overlay.png", "instances.csv", "metadata.json"},
                    )
                    saved = json.loads(archive.read("metadata.json"))
                    self.assertEqual(saved["input_sha256"], "abc123")
            finally:
                bundle.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()

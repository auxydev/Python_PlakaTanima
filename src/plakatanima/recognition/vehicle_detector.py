"""Araç tespiti ve sınıflandırma (otomobil, motosiklet, kamyon, otobüs ...)."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from pathlib import Path

import cv2
import numpy as np

from plakatanima.core.vehicle import COCO_VEHICLE_CLASSES, vehicle_type_from_class_name
from plakatanima.recognition.model_store import ModelError
from plakatanima.recognition.types import BBox, VehicleDetection

log = logging.getLogger(__name__)

_COCO_VEHICLE_IDS = np.array(sorted(COCO_VEHICLE_CLASSES))
_COCO_VEHICLE_NAMES = {2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}


def onnx_providers(device: str) -> list[str]:
    import onnxruntime as ort

    available = ort.get_available_providers()
    if device == "cpu":
        return ["CPUExecutionProvider"]
    preferred = ["CUDAExecutionProvider", "DmlExecutionProvider", "CoreMLExecutionProvider"]
    providers = [p for p in preferred if p in available]
    if device == "cuda" and "CUDAExecutionProvider" not in providers:
        log.warning("CUDA bulunamadı, işlemci (CPU) kullanılacak")
    return [*providers, "CPUExecutionProvider"]


def nms(boxes: np.ndarray, scores: np.ndarray, iou_threshold: float) -> list[int]:
    """Sınıftan bağımsız non-maximum suppression. ``boxes``: (N, 4) xyxy."""
    if len(boxes) == 0:
        return []
    x1, y1, x2, y2 = boxes.T
    areas = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
    order = scores.argsort()[::-1]
    keep: list[int] = []
    while order.size:
        i = int(order[0])
        keep.append(i)
        rest = order[1:]
        w = np.clip(np.minimum(x2[i], x2[rest]) - np.maximum(x1[i], x1[rest]), 0, None)
        h = np.clip(np.minimum(y2[i], y2[rest]) - np.maximum(y1[i], y1[rest]), 0, None)
        inter = w * h
        iou = inter / (areas[i] + areas[rest] - inter + 1e-9)
        order = rest[iou <= iou_threshold]
    return keep


class VehicleDetector(ABC):
    @abstractmethod
    def detect(self, frame: np.ndarray) -> list[VehicleDetection]:
        """BGR karedeki araçları döndürür."""


class NullVehicleDetector(VehicleDetector):
    """Araç tespiti kapalı: plakalar 'bilinmiyor' tipiyle işlenir."""

    def detect(self, frame: np.ndarray) -> list[VehicleDetection]:
        return []


class YoloxVehicleDetector(VehicleDetector):
    """YOLOX (COCO) ONNX modeli ile araç tespiti; yalnızca onnxruntime gerektirir."""

    def __init__(
        self,
        model_path: Path,
        *,
        confidence: float = 0.35,
        nms_iou: float = 0.45,
        device: str = "auto",
    ) -> None:
        import onnxruntime as ort

        try:
            self._session = ort.InferenceSession(str(model_path), providers=onnx_providers(device))
        except Exception as exc:  # onnxruntime kendi hata tiplerini kullanır
            raise ModelError(f"Araç modeli yüklenemedi ({model_path}): {exc}") from exc
        model_input = self._session.get_inputs()[0]
        self._input_name = model_input.name
        h, w = model_input.shape[2], model_input.shape[3]
        self._input_size = (h if isinstance(h, int) else 640, w if isinstance(w, int) else 640)
        self._grids, self._strides = self._make_grids(*self._input_size)
        self.confidence = confidence
        self.nms_iou = nms_iou

    @staticmethod
    def _make_grids(height: int, width: int) -> tuple[np.ndarray, np.ndarray]:
        grids, strides = [], []
        for stride in (8, 16, 32):
            hs, ws = height // stride, width // stride
            xv, yv = np.meshgrid(np.arange(ws), np.arange(hs))
            grids.append(np.stack((xv, yv), 2).reshape(-1, 2))
            strides.append(np.full((hs * ws, 1), stride))
        return np.concatenate(grids).astype(np.float32), np.concatenate(strides).astype(np.float32)

    def _preprocess(self, frame: np.ndarray) -> tuple[np.ndarray, float]:
        h, w = self._input_size
        ratio = min(h / frame.shape[0], w / frame.shape[1])
        resized = cv2.resize(
            frame,
            (int(frame.shape[1] * ratio), int(frame.shape[0] * ratio)),
            interpolation=cv2.INTER_LINEAR,
        )
        padded = np.full((h, w, 3), 114, dtype=np.uint8)
        padded[: resized.shape[0], : resized.shape[1]] = resized
        blob = np.ascontiguousarray(padded.transpose(2, 0, 1)[None], dtype=np.float32)
        return blob, ratio

    def detect(self, frame: np.ndarray) -> list[VehicleDetection]:
        blob, ratio = self._preprocess(frame)
        out = self._session.run(None, {self._input_name: blob})[0][0].copy()
        # Resmi YOLOX ONNX çıktısı ham ızgara ofsetleri içerir; çözülmemişse çöz.
        # (log ölçeğindeki ham genişlik/yükseklik değerleri hiçbir zaman 32'yi geçmez.)
        if out.shape[0] == len(self._grids) and out[:, 2:4].max() < 32:
            out[:, :2] = (out[:, :2] + self._grids) * self._strides
            out[:, 2:4] = np.exp(out[:, 2:4]) * self._strides

        scores = out[:, 4:5] * out[:, 5 + _COCO_VEHICLE_IDS]
        best = scores.argmax(axis=1)
        conf = scores.max(axis=1)
        mask = conf >= self.confidence
        if not mask.any():
            return []
        cx, cy, bw, bh = out[mask, :4].T
        boxes = np.stack([cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2], axis=1) / ratio
        conf, best = conf[mask], best[mask]

        height, width = frame.shape[:2]
        detections = []
        for i in nms(boxes, conf, self.nms_iou):
            class_id = int(_COCO_VEHICLE_IDS[best[i]])
            detections.append(
                VehicleDetection(
                    bbox=BBox.from_xyxy(boxes[i]).clip(width, height),
                    vehicle_type=COCO_VEHICLE_CLASSES[class_id],
                    confidence=float(conf[i]),
                    class_name=_COCO_VEHICLE_NAMES[class_id],
                )
            )
        return detections


class UltralyticsVehicleDetector(VehicleDetector):
    """Ultralytics YOLO (.pt) modelleri; özel eğitilmiş sınıflar (van, minibus ...) desteklenir.

    Kurulum: ``pip install "plakatanima[yolo]"`` (AGPL-3.0, PyTorch gerektirir).
    """

    def __init__(self, model: str, *, confidence: float = 0.35, device: str = "auto") -> None:
        try:
            from ultralytics import YOLO
        except ImportError as exc:
            raise ModelError(
                'Ultralytics kurulu değil. Kurmak için: pip install "plakatanima[yolo]"'
            ) from exc
        self._model = YOLO(model)
        names: dict[int, str] = dict(self._model.names)
        self._class_map = {
            idx: vtype
            for idx, name in names.items()
            if (vtype := vehicle_type_from_class_name(name))
        }
        if not self._class_map:
            raise ModelError(f"{model} modelinde araç sınıfı bulunamadı: {sorted(names.values())}")
        self._names = names
        self.confidence = confidence
        self._device = {"auto": None, "cpu": "cpu", "cuda": 0}[device]

    def detect(self, frame: np.ndarray) -> list[VehicleDetection]:
        result = self._model.predict(
            frame,
            conf=self.confidence,
            classes=list(self._class_map),
            agnostic_nms=True,
            device=self._device,
            verbose=False,
        )[0]
        boxes = result.boxes
        xyxy = boxes.xyxy.cpu().numpy()
        classes = boxes.cls.cpu().numpy().astype(int)
        confs = boxes.conf.cpu().numpy()
        return [
            VehicleDetection(
                bbox=BBox.from_xyxy(box),
                vehicle_type=self._class_map[int(cls)],
                confidence=float(conf),
                class_name=self._names[int(cls)],
            )
            for box, cls, conf in zip(xyxy, classes, confs, strict=True)
            if int(cls) in self._class_map
        ]

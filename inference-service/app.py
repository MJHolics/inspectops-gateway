"""InspectOps 추론 서비스 — 엣지 CNN(ONNX)을 HTTP로 노출한다.

모델·전처리·심각도 매핑은 `vlm-defect-inspector/space/app.py`(HF Space 라이브 데모)와 동일하다.
Gateway(Spring)가 이 서비스를 호출한다. 이 서비스는 판정만 하고 상태를 갖지 않는다.

부하 실험용 손잡이 하나: 환경변수 `EXTRA_LATENCY_MS`.
엣지 CNN은 수 ms라 Gateway 쪽 병목이 드러나지 않는다. 느린 판정 경로(VLM 트리아지 1장 14.7s 실측)를
흉내 낼 때만 켠다. 켜져 있으면 응답의 `injected_latency_ms`에 그대로 적어 숨기지 않는다.
"""
import asyncio
import io
import os
import time
from pathlib import Path

import numpy as np
import onnxruntime as ort
from fastapi import FastAPI, File, HTTPException, UploadFile
from PIL import Image, UnidentifiedImageError

MODEL_PATH = Path(os.environ.get("MODEL_PATH", Path(__file__).parent / "model.onnx"))
EXTRA_LATENCY_MS = float(os.environ.get("EXTRA_LATENCY_MS", "0"))
MODEL_VERSION = os.environ.get("MODEL_VERSION", "mobilenet_v3_small_fp32")

CLASSES = ["crazing", "inclusion", "patches",
           "pitted_surface", "rolled-in_scale", "scratches"]
SEVERITY = {"crazing": "low", "inclusion": "medium", "patches": "low",
            "pitted_surface": "high", "rolled-in_scale": "medium", "scratches": "high"}
IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
IMAGENET_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)

_so = ort.SessionOptions()
_so.intra_op_num_threads = 1
_sess = ort.InferenceSession(str(MODEL_PATH), _so, providers=["CPUExecutionProvider"])
_input_name = _sess.get_inputs()[0].name

app = FastAPI(title="InspectOps inference", version="0.1.0")


def _preprocess(img: Image.Image, size: int = 224) -> np.ndarray:
    img = img.convert("L").resize((size, size), Image.BILINEAR)
    x = np.asarray(img, dtype=np.float32) / 255.0
    x = np.stack([x, x, x], axis=0)
    x = (x - IMAGENET_MEAN[:, None, None]) / IMAGENET_STD[:, None, None]
    return x[None].astype(np.float32)


def _softmax(z: np.ndarray) -> np.ndarray:
    z = z - z.max()
    e = np.exp(z)
    return e / e.sum()


@app.get("/healthz")
def healthz():
    return {"status": "ok", "model_version": MODEL_VERSION}


@app.post("/v1/inspect")
async def inspect(image: UploadFile = File(...)):
    raw = await image.read()
    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
    except (UnidentifiedImageError, OSError):
        raise HTTPException(status_code=422, detail="이미지로 읽을 수 없는 입력")

    t0 = time.perf_counter()
    # onnxruntime 호출은 동기다 — 이벤트 루프를 막지 않게 스레드로 넘긴다.
    logits = await asyncio.to_thread(lambda: _sess.run(None, {_input_name: _preprocess(img)})[0][0])
    model_ms = (time.perf_counter() - t0) * 1000

    if EXTRA_LATENCY_MS > 0:
        await asyncio.sleep(EXTRA_LATENCY_MS / 1000)

    probs = _softmax(logits)
    idx = int(probs.argmax())
    cls = CLASSES[idx]
    return {
        "defect_class": cls,
        "confidence": float(probs[idx]),
        "severity": SEVERITY[cls],
        "probabilities": {CLASSES[i]: float(probs[i]) for i in range(len(CLASSES))},
        "model_version": MODEL_VERSION,
        "model_ms": round(model_ms, 3),
        "injected_latency_ms": EXTRA_LATENCY_MS,
    }

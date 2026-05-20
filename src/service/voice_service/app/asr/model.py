from __future__ import annotations

import io
import time
from typing import Optional

import numpy as np
import soundfile as sf
import torch

SAMPLE_RATE = 16000
MODEL_ID = "Qwen/Qwen3-ASR-0.6B"


class AsrModel:
    def __init__(self) -> None:
        self._model = None
        self._gpu_name: Optional[str] = None

    @property
    def loaded(self) -> bool:
        return self._model is not None

    @property
    def gpu(self) -> str:
        return self._gpu_name or ("cuda" if torch.cuda.is_available() else "cpu")

    def load(self) -> None:
        if self._model is not None:
            return
        from qwen_asr import Qwen3ASRModel

        device_map = "cuda:0" if torch.cuda.is_available() else "cpu"
        dtype = torch.bfloat16 if torch.cuda.is_available() else torch.float32
        t0 = time.perf_counter()
        self._model = Qwen3ASRModel.from_pretrained(
            MODEL_ID,
            dtype=dtype,
            device_map=device_map,
            max_new_tokens=256,
        )
        if torch.cuda.is_available():
            self._gpu_name = torch.cuda.get_device_name(0)
        print(f"[asr] loaded {MODEL_ID} in {time.perf_counter() - t0:.2f}s on {self.gpu}")

    def transcribe(self, wav_bytes: bytes, context: Optional[str] = None) -> tuple[str, float, int]:
        if self._model is None:
            raise RuntimeError("AsrModel not loaded")
        try:
            audio, sr = sf.read(io.BytesIO(wav_bytes), dtype="float32")
        except Exception as exc:
            raise ValueError(f"wav decode failed: {exc}") from exc
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        if sr != SAMPLE_RATE:
            import librosa

            audio = librosa.resample(audio, orig_sr=sr, target_sr=SAMPLE_RATE)
        audio = audio.astype(np.float32)

        kwargs: dict = {"audio": (audio, SAMPLE_RATE), "language": "Korean"}
        if context:
            kwargs["context"] = context

        t0 = time.perf_counter()
        results = self._model.transcribe(**kwargs)
        dt_ms = (time.perf_counter() - t0) * 1000
        text = results[0].text.strip()
        return text, dt_ms, int(audio.shape[0])

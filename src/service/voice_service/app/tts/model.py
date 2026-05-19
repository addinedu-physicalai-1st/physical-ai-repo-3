from __future__ import annotations

import io
import time
from pathlib import Path
from typing import Optional

import numpy as np
import soundfile as sf
import torch

MODEL_ID = "Qwen/Qwen3-TTS-12Hz-0.6B-Base"
REF_DIR = Path(__file__).parent / "ref"
REF_WAV = REF_DIR / "reference.wav"
REF_TXT = REF_DIR / "reference_transcript.txt"


class TtsModel:
    def __init__(self) -> None:
        self._model = None
        self._ref_audio: Optional[np.ndarray] = None
        self._ref_sr: Optional[int] = None
        self._ref_text: Optional[str] = None
        self._gpu_name: Optional[str] = None

    @property
    def loaded(self) -> bool:
        return self._model is not None and self._ref_audio is not None

    @property
    def gpu(self) -> str:
        return self._gpu_name or ("cuda" if torch.cuda.is_available() else "cpu")

    @property
    def ref_seconds(self) -> float:
        if self._ref_audio is None or not self._ref_sr:
            return 0.0
        return float(self._ref_audio.shape[0]) / float(self._ref_sr)

    def load(self) -> None:
        if self.loaded:
            return
        from qwen_tts import Qwen3TTSModel

        if not REF_WAV.exists() or not REF_TXT.exists():
            raise FileNotFoundError(
                f"reference assets missing in {REF_DIR}: "
                f"reference.wav and reference_transcript.txt required"
            )

        device_map = "cuda:0" if torch.cuda.is_available() else "cpu"
        dtype = torch.bfloat16 if torch.cuda.is_available() else torch.float32
        t0 = time.perf_counter()
        self._model = Qwen3TTSModel.from_pretrained(
            MODEL_ID,
            device_map=device_map,
            dtype=dtype,
        )
        if torch.cuda.is_available():
            self._gpu_name = torch.cuda.get_device_name(0)

        audio, sr = sf.read(REF_WAV, dtype="float32")
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        self._ref_audio = audio.astype(np.float32)
        self._ref_sr = int(sr)
        self._ref_text = REF_TXT.read_text(encoding="utf-8").strip()

        print(
            f"[tts] loaded {MODEL_ID} in {time.perf_counter() - t0:.2f}s "
            f"on {self.gpu}  ref={self.ref_seconds:.2f}s @ {self._ref_sr}Hz"
        )

    def synthesize(self, text: str) -> tuple[bytes, int, float, float]:
        if not self.loaded:
            raise RuntimeError("TtsModel not loaded")
        t0 = time.perf_counter()
        wavs, sr = self._model.generate_voice_clone(
            text=text,
            language="Korean",
            ref_audio=(self._ref_audio, self._ref_sr),
            ref_text=self._ref_text,
        )
        dt_ms = (time.perf_counter() - t0) * 1000

        audio = wavs[0] if isinstance(wavs, (list, tuple)) else wavs
        if isinstance(audio, torch.Tensor):
            audio = audio.detach().cpu().float().numpy()
        audio = np.asarray(audio).astype(np.float32).flatten()
        duration = float(audio.shape[0]) / float(sr)

        buf = io.BytesIO()
        sf.write(buf, audio, int(sr), format="WAV", subtype="PCM_16")
        return buf.getvalue(), int(sr), dt_ms, duration

from __future__ import annotations

import time
from typing import Optional

import torch

MODEL_ID = "Qwen/Qwen2.5-3B-Instruct"


class LlmModel:
    def __init__(self) -> None:
        self._model = None
        self._tokenizer = None
        self._gpu_name: Optional[str] = None

    @property
    def loaded(self) -> bool:
        return self._model is not None and self._tokenizer is not None

    @property
    def gpu(self) -> str:
        return self._gpu_name or ("cuda" if torch.cuda.is_available() else "cpu")

    def load(self) -> None:
        if self.loaded:
            return
        from transformers import AutoModelForCausalLM, AutoTokenizer

        device_map = "cuda:0" if torch.cuda.is_available() else "cpu"
        dtype = torch.bfloat16 if torch.cuda.is_available() else torch.float32
        t0 = time.perf_counter()
        self._tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
        self._model = AutoModelForCausalLM.from_pretrained(
            MODEL_ID,
            dtype=dtype,
            device_map=device_map,
        )
        if torch.cuda.is_available():
            self._gpu_name = torch.cuda.get_device_name(0)
        print(f"[llm] loaded {MODEL_ID} in {time.perf_counter() - t0:.2f}s on {self.gpu}")

    def generate(self, system_prompt: str, user_text: str, max_new_tokens: int = 256) -> tuple[str, float]:
        if not self.loaded:
            raise RuntimeError("LlmModel not loaded")
        msgs = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text},
        ]
        prompt = self._tokenizer.apply_chat_template(
            msgs, tokenize=False, add_generation_prompt=True
        )
        inputs = self._tokenizer(prompt, return_tensors="pt").to(self._model.device)
        input_len = inputs["input_ids"].shape[-1]
        t0 = time.perf_counter()
        with torch.inference_mode():
            out = self._model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                do_sample=False,
                pad_token_id=self._tokenizer.eos_token_id,
            )
        dt_ms = (time.perf_counter() - t0) * 1000
        new_tokens = out[0, input_len:]
        raw = self._tokenizer.decode(new_tokens, skip_special_tokens=True).strip()
        return raw, dt_ms

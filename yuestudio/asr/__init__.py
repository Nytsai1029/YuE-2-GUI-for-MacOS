"""Speech recognition on rendered takes, isolated in its own process.

The provider runs in a single-worker process pool (spawned, not forked) so a Metal crash
or memory spike can never take the studio server down, and the model can be released
between takes so it never competes with YuE2 for unified memory. mlx-whisper is used when
installed (``pip install -e .[asr]``); otherwise the Director simply skips ASR checks.
"""
from __future__ import annotations

import importlib.util
import logging
import multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor

log = logging.getLogger("yuestudio.asr")


def _transcribe(path: str, model: str, language: str | None, temperature: float) -> dict:
    import mlx_whisper
    import numpy as np
    import soundfile as sf
    from scipy import signal

    audio, sr = sf.read(path, dtype="float32", always_2d=True)
    mono = audio.mean(axis=1)
    if sr != 16000:
        g = np.gcd(16000, sr)
        mono = signal.resample_poly(mono, 16000 // g, sr // g).astype(np.float32)
    result = mlx_whisper.transcribe(
        mono, path_or_hf_repo=model, language=language, word_timestamps=True,
        condition_on_previous_text=False, temperature=temperature, no_speech_threshold=0.6,
        compression_ratio_threshold=2.4, hallucination_silence_threshold=2.0, verbose=None)
    words = []
    for seg in result.get("segments", []):
        if seg.get("no_speech_prob", 0) > 0.8 and seg.get("avg_logprob", 0) < -1.0:
            continue
        for w in seg.get("words", []) or []:
            words.append({"text": w["word"].strip(), "start": float(w["start"]), "end": float(w["end"]),
                          "prob": float(w.get("probability", 0))})
    return {"text": result.get("text", ""), "language": result.get("language"), "words": words}


class ASR:
    def __init__(self, settings_fn):
        self.settings_fn = settings_fn
        self.pool: ProcessPoolExecutor | None = None

    def provider(self) -> str | None:
        cfg = self.settings_fn()["asr"]
        if not cfg.get("enabled", True):
            return None
        if importlib.util.find_spec("mlx_whisper") is not None:
            return "mlx-whisper"
        return None

    def available(self) -> bool:
        return self.provider() is not None

    def transcribe(self, path: str, language: str | None = None, passes: int = 1) -> list[dict] | None:
        if not self.available():
            return None
        cfg = self.settings_fn()["asr"]
        if self.pool is None:
            self.pool = ProcessPoolExecutor(max_workers=1, mp_context=mp.get_context("spawn"))
        runs = []
        for i in range(max(1, passes)):
            try:
                runs.append(self.pool.submit(_transcribe, path, cfg["model"], language, 0.0 if i == 0 else 0.2)
                            .result(timeout=900))
            except Exception as error:  # the pool process may have died; recreate next time
                log.warning("ASR failed: %s", error)
                self.release()
                break
        return runs or None

    def release(self) -> None:
        if self.pool is not None:
            self.pool.shutdown(wait=False, cancel_futures=True)
            self.pool = None

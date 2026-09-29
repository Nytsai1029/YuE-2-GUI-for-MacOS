"""Wire protocol between the studio server and an engine worker process.

JSON lines. Requests go to the worker's stdin; responses and events come back on a
private copy of the worker's original stdout (the worker redirects fd 1 to stderr so
library progress bars can never corrupt the protocol).

Request:   {"v": 1, "id": "<str>", "m": "<method>", "p": {...}}
Response:  {"id": "<str>", "ok": true, "r": {...}}
           {"id": "<str>", "ok": false, "err": {"code": "<CODE>", "msg": "...", "trace": "..."}}
Event:     {"ev": "<kind>", "id": "<request id or null>", ...}

Control messages ("cancel", "ping") are handled by the worker's reader thread and never
wait for the busy main thread. Bulk data (tokens, noise, latents, audio) always travels
as files inside the request's job directory, never inside JSON.

This module must stay importable on Python 3.12 with the standard library only.
"""

PROTOCOL_VERSION = 1

# Methods served by the main (GPU) thread, one at a time.
METHODS = (
    "hello",       # -> {protocol, python, backend, lyra_version, fake}
    "introspect",  # -> capabilities detected in the installed lyra/yue2
    "load",        # {model, vae, converted_dir, precision, memory_budget_gib} -> {weights, load_seconds}
    "unload",
    "plan",        # {job_dir, style, lyrics, cot, seed, abc?, abc_sampling?} -> PlanOut
    "semantic",    # {job_dir, plan_dir, seed, sampling?, chunk_every?} -> SemanticOut
    "render",      # {job_dir, plan_dir, tokens_path, ode_steps, noise_seed} -> AudioOut
    "abc_check",   # {abc, compare_to?, allow_tempo_change?} -> {ok, error?, report?, compare?}
    "shutdown",
)

# Control methods handled immediately by the reader thread.
CONTROL = ("cancel", "ping")

# Error codes.
E_CANCELLED = "CANCELLED"
E_OOM = "OOM"
E_BAD_REQUEST = "BAD_REQUEST"
E_BAD_ABC = "BAD_ABC"
E_LOAD = "LOAD"
E_NOT_LOADED = "NOT_LOADED"
E_CONTEXT = "CONTEXT"
E_INTERNAL = "INTERNAL"

# Event kinds.
EV_READY = "ready"
EV_PROGRESS = "progress"      # {id, phase, done, total}
EV_TOKENS = "tokens"          # {id, phase, start, chunk:[int...]} streamed semantic tokens
EV_HEARTBEAT = "heartbeat"    # {rss, busy}
EV_LOG = "log"                # {level, msg}

# Semantic codec frame rate: one frame per 40 ms (48 kHz * 0.04 = 1920 samples).
FRAME_SECONDS = 0.04
SAMPLES_PER_FRAME = 1920
SAMPLE_RATE = 48000
CONTEXT = 24576

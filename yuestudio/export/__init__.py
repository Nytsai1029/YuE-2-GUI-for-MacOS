"""Delivery files: LRC (synced lyrics), MIDI (from the score), MP3 (ffmpeg if present),
AI-disclosure metadata, and the recipe JSON that makes every take reproducible."""
from __future__ import annotations

import json
import shutil
import struct
import subprocess
from pathlib import Path

from ..abc.score import Score

DISCLOSURE = "AI-generated with YuE2 (M-A-P/HKUST) via YuE Studio. Model weights: CC BY-NC 4.0 with creator permission."


def lrc(lines: list[dict], title: str = "", artist: str = "") -> str:
    """lines: [{"text", "start"}] in seconds (display text, never the normalised sung text)."""
    out = []
    if title:
        out.append(f"[ti:{title}]")
    if artist:
        out.append(f"[ar:{artist}]")
    out.append("[re:YuE Studio]")
    for ln in sorted(lines, key=lambda x: x["start"]):
        m, s = divmod(max(0.0, ln["start"]), 60)
        out.append(f"[{int(m):02d}:{s:05.2f}]{ln['text'].strip()}")
    return "\n".join(out) + "\n"


def _vlq(n: int) -> bytes:
    out = [n & 0x7F]
    n >>= 7
    while n:
        out.append((n & 0x7F) | 0x80)
        n >>= 7
    return bytes(reversed(out))


def _track(events: list[tuple[int, bytes]]) -> bytes:
    events.sort(key=lambda e: e[0])
    data, last = b"", 0
    for tick, payload in events:
        data += _vlq(tick - last) + payload
        last = tick
    data += b"\x00\xff\x2f\x00"
    return b"MTrk" + struct.pack(">I", len(data)) + data


def midi(score: Score, path: str, ppq: int = 480) -> None:
    from ..analysis.metrics import QUALITY_TONES, parse_chord

    def ticks(q):
        return int(round(float(q) * ppq))

    tempo = int(60_000_000 / score.bpm)
    meta = [(0, b"\xff\x51\x03" + tempo.to_bytes(3, "big")),
            (0, b"\xff\x58\x04" + bytes([score.meter[0], {1: 0, 2: 1, 4: 2, 8: 3, 16: 4}.get(score.meter[1], 2), 24, 8]))]
    tracks = [_track(meta)]
    for ch, (name, notes, program) in enumerate([("Vocal", score.vocal, 53), ("Ins", score.ins, 0)]):
        ev = [(0, b"\xff\x03" + _vlq(len(name)) + name.encode()), (0, bytes([0xC0 | ch, program]))]
        for n in notes:
            ev.append((ticks(n.onset), bytes([0x90 | ch, n.pitch, 90])))
            ev.append((ticks(n.end), bytes([0x80 | ch, n.pitch, 0])))
        tracks.append(_track(ev))
    ev = [(0, b"\xff\x03\x06Chords"), (0, bytes([0xC2, 0]))]
    timeline = score.chord_timeline() + [(score.quarters, None)]
    for (t, sym), (t2, _) in zip(timeline, timeline[1:]):
        c = parse_chord(sym) if sym else None
        if not c:
            continue
        root = 48 + c["root"]
        for iv in QUALITY_TONES[c["quality"]]:
            ev.append((ticks(t), bytes([0x92, root + iv, 60])))
            ev.append((ticks(t2) - 1, bytes([0x82, root + iv, 0])))
    tracks.append(_track(ev))
    header = b"MThd" + struct.pack(">IHHH", 6, 1, len(tracks), ppq)
    Path(path).write_bytes(header + b"".join(tracks))


def mp3(src: str, dst: str, title: str = "", bitrate: str = "320k") -> bool:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return False
    cmd = [ffmpeg, "-y", "-loglevel", "error", "-i", src, "-codec:a", "libmp3lame", "-b:a", bitrate,
           "-metadata", f"title={title}", "-metadata", f"comment={DISCLOSURE}", "-metadata", "encoded_by=YuE Studio", dst]
    return subprocess.run(cmd, capture_output=True).returncode == 0


def tag_flac(path: str, title: str = "") -> None:
    """Vorbis comments with the AI disclosure (soundfile writes basic tags)."""
    try:
        import soundfile as sf

        with sf.SoundFile(path, "r+") as f:
            f.title = title or f.title
            f.comment = DISCLOSURE
            f.software = "YuE Studio"
    except Exception:
        pass


def recipe(path: str, data: dict) -> None:
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

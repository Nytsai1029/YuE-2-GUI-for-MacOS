"""Application services shared by the API and the CLI."""
from __future__ import annotations

import random
import time

from .lyrics.doc import parse as parse_lyrics
from .lyrics.lint import LintContext, lint
from .style import StyleFields, compose, genre_info, is_instrumental, lint_style, vocal_bpm


def check(lyrics: str, fields: dict | None, lexicon: dict[str, str]) -> dict:
    """Everything the Write view needs in one call: lyric + style lint, sung text, estimate."""
    f = StyleFields.from_dict(fields)
    lang = parse_lyrics(lyrics).language()
    style = compose(f, lang)
    info = genre_info(style, f)
    bpm = float(f.bpm or 96)
    vbpm = vocal_bpm(style, f)
    ctx = LintContext(bpm=bpm, vocal_bpm=vbpm, edm=info["edm"], lexicon=lexicon, style=style,
                      instrumental=is_instrumental(f))
    result = lint(lyrics, ctx)
    has_lyrics = bool(result["mapping"])
    style_issues = lint_style(style, f, result["language"], has_lyrics)
    blocking = [i for i in result["issues"] + style_issues if i["severity"] == "error"]
    return {**result, "style": style, "style_issues": style_issues, "bpm": bpm, "vocal_bpm": vbpm,
            "genre": info, "blocking": len(blocking), "fields": f.to_dict(), "instrumental": is_instrumental(f)}


def create_draft(db, song_id: str, lyrics: str, fields: dict | None) -> dict:
    lexicon = db.lexicon()
    c = check(lyrics, fields, lexicon)
    f = c["fields"]
    draft = db.insert("drafts", {
        "song_id": song_id, "lyrics": lyrics, "style_fields": f, "style": c["style"], "sung": c["sung"],
        "mapping": c["mapping"], "lint": {"issues": c["issues"], "style_issues": c["style_issues"],
                                          "estimate": c["estimate"], "blocking": c["blocking"]},
        "bpm": c["bpm"], "vocal_bpm": c["vocal_bpm"], "language": c["language"],
        "gender": f.get("gender") or "female"})
    db.update("songs", song_id, updated=time.time())
    return draft


def create_song(db, title: str) -> dict:
    return db.insert("songs", {"title": title or "Untitled", "updated": time.time(),
                               "cover_seed": random.randrange(1, 2**31)})


def create_take(db, song_id: str, draft_id: str, preset: str, options: dict | None = None) -> dict:
    options = dict(options or {})
    options.setdefault("seed", random.randrange(1, 2**31))
    return db.insert("takes", {"song_id": song_id, "draft_id": draft_id, "preset": preset, "options": options,
                               "status": "queued", "stage": "queued"})

from yuestudio.style import StyleFields, compose, genre_info, lint_style, vocal_bpm


def rules(style, fields=None, lang="en", has_lyrics=True):
    fields = fields or StyleFields(override=style)
    return {i["rule"] for i in lint_style(style, fields, lang, has_lyrics)}


def test_compose_follows_official_order():
    f = StyleFields(genres=["city pop"], moods=["nostalgic"], timbre=["bright"],
                    instruments=["groovy bass", "electric piano"], harmony="color", bpm=112)
    s = compose(f, "zh")
    assert s.startswith("Chinese, city pop, nostalgic, bright female vocal, controlled delivery")
    assert s.endswith("112 BPM")
    assert not rules(s, f, "zh") - {"style.bpm"}


def test_bad_style_is_caught():
    s = "English, screaming ballad in the style of Taylor Swift, no drums, instrumental"
    found = rules(s, lang="zh")
    assert {"style.language", "style.instrumental", "style.artist", "style.intensity", "style.negation"} <= found


def test_edm_half_time_and_bpm_range():
    f = StyleFields(genres=["artcore"], bpm=175)
    s = compose(f, "en")
    assert genre_info(s, f)["half_time"]
    assert vocal_bpm(s, f) == 87.5
    assert "style.bpm" in rules(s, f)          # the half-time hint
    assert vocal_bpm("English, pop, 120 BPM") == 120


def test_instrumental_style():
    f = StyleFields(gender="none", genres=["cinematic pop"], instruments=["acoustic piano"], bpm=84)
    s = compose(f)
    assert "instrumental" in s and s.endswith("no vocals")
    assert not rules(s, f, has_lyrics=False)
    assert "style.instrumental" in rules(s, f, has_lyrics=True)

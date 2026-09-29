import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "fake_lyra"))

LYRICS = """[Intro]

[Verse]
城市的灯火 慢慢亮起来
我走在雨里 想起了你
街角的咖啡 还冒着热气
你说的再见 还在耳边

[Pre-Chorus]
如果时间能倒流
我会紧紧牵你的手

[Chorus]
我们一起飞 越过这黑夜
不再害怕 不再后退
星光在闪烁 照亮你的脸
这一次 我不会走远

[Verse]
Streetlights flicker on the avenue
Every window glowing just for you
I keep the letters that you never sent
Counting the moments that we spent

[Chorus]
我们一起飞 越过这黑夜
不再害怕 不再后退
星光在闪烁 照亮你的脸
这一次 我不会走远

[Outro]
"""


@pytest.fixture
def lyrics():
    return LYRICS


@pytest.fixture
def faults(monkeypatch):
    def set_(spec: str):
        monkeypatch.setenv("YUESTUDIO_FAKE_FAULTS", spec)
    set_("")
    return set_


@pytest.fixture
def compose():
    from lyra._composer import compose as c
    return c


@pytest.fixture(autouse=True)
def fast_fake(monkeypatch):
    monkeypatch.setenv("YUESTUDIO_FAKE_NAR_S", "0.2")
    monkeypatch.setenv("YUESTUDIO_FAKE_TOKS", "0")
    monkeypatch.setenv("YUESTUDIO_FAKE_LOAD_S", "0")
    os.environ.pop("YUESTUDIO_FAKE_TTS", None)

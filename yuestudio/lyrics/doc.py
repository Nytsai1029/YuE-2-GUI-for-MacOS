"""Parse editor text into sections while keeping exact editor line numbers."""
from __future__ import annotations

from dataclasses import dataclass, field

from . import syllables
from .tags import INSTRUMENTAL_OK, canonical, parse_repeat_line, parse_tag_line, repeat_count
from .text import line_language


@dataclass
class Line:
    index: int          # 0-based editor line
    text: str
    group: int = 0      # blank-line separated group inside the section

    @property
    def syllables(self) -> int:
        return syllables.count(self.text)

    @property
    def language(self) -> str:
        return line_language(self.text)


@dataclass
class Section:
    raw_tag: str | None
    tag: str | None                 # canonical tag or None if unknown/missing
    tag_line: int | None
    lines: list[Line] = field(default_factory=list)
    repeat: int = 1                 # from "[Chorus x2]"
    blank_before: bool = True

    @property
    def instrumental(self) -> bool:
        return not self.lines

    @property
    def kind(self) -> str:
        return (self.tag or "Verse").lower()

    def text(self) -> str:
        return "\n".join(line.text for line in self.lines)


@dataclass
class RepeatDirective:
    index: int
    tag: str
    count: int


@dataclass
class LyricDoc:
    text: str
    sections: list[Section]
    repeats: list[RepeatDirective]
    lines: list[str]

    @property
    def sung_lines(self) -> list[Line]:
        return [line for s in self.sections for line in s.lines]

    def language(self) -> str:
        counts: dict[str, int] = {}
        for line in self.sung_lines:
            lang = line.language
            if lang:
                counts[lang] = counts.get(lang, 0) + max(1, line.syllables)
        if not counts:
            return "en"
        zh, en = counts.get("zh", 0) + counts.get("mixed", 0) / 2, counts.get("en", 0) + counts.get("mixed", 0) / 2
        if zh >= en:
            return "zh"
        return "en" if en else max(counts, key=counts.get)

    def expanded(self) -> list[Section]:
        """The section sequence the singer should perform: repeat suffixes and repeat
        directives resolved, unknown tags treated as verses."""
        out: list[Section] = []
        directives = {d.index: d for d in self.repeats}
        last_by_tag: dict[str, Section] = {}
        items = sorted([(s.tag_line if s.tag_line is not None else (s.lines[0].index if s.lines else -1), "s", s)
                        for s in self.sections] + [(d.index, "d", d) for d in self.repeats], key=lambda t: t[0])
        for _, kind, item in items:
            if kind == "s":
                sec = item
                if sec.repeat > 1 and sec.lines:
                    lines = []
                    for r in range(sec.repeat):
                        lines += [Line(li.index, li.text, group=r) for li in sec.lines]
                    sec = Section(sec.raw_tag, sec.tag, sec.tag_line, lines, 1, sec.blank_before)
                out.append(sec)
                if sec.tag:
                    last_by_tag[sec.tag] = sec
            else:
                d = directives[item.index]
                source = last_by_tag.get(d.tag)
                if source is not None:
                    for _ in range(d.count):
                        out.append(Section(source.raw_tag, source.tag, None, list(source.lines), 1, True))
        return out


def parse(text: str) -> LyricDoc:
    raw_lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    sections: list[Section] = []
    repeats: list[RepeatDirective] = []
    current: Section | None = None
    group = 0
    prev_blank = True
    for i, raw in enumerate(raw_lines):
        stripped = raw.strip()
        if not stripped:
            if current is not None and current.lines:
                group += 1
            prev_blank = True
            continue
        tag = parse_tag_line(stripped)
        rep = None if tag else parse_repeat_line(stripped)
        if tag is not None:
            current = Section(raw_tag=tag, tag=canonical(tag), tag_line=i, repeat=repeat_count(stripped),
                              blank_before=prev_blank or i == 0)
            sections.append(current)
            group = 0
        elif rep is not None:
            repeats.append(RepeatDirective(i, rep[0], rep[1]))
            current = None
        else:
            if current is None:
                current = Section(raw_tag=None, tag=None, tag_line=None, blank_before=True)
                sections.append(current)
                group = 0
            current.lines.append(Line(i, raw, group))
        prev_blank = False
    return LyricDoc(text=text, sections=sections, repeats=repeats, lines=raw_lines)


def is_instrumental_tag(tag: str | None) -> bool:
    return tag in INSTRUMENTAL_OK

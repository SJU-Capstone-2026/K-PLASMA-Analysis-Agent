"""Project allowed prose fields from provider JSON without exposing its wire format."""

import json
from dataclasses import dataclass, field
from typing import Any

from .core.composition import fill_value_references


@dataclass
class _Frame:
    path: tuple
    kind: str
    state: str
    key: str = ""
    index: int = 0
    keys: set[str] = field(default_factory=set)


class _JsonStrings:
    """Incremental JSON structure/string decoder; final schema validation stays with the caller."""

    def __init__(self):
        self.strings: dict[tuple, str] = {}
        self.complete: set[tuple] = set()
        self.stack: list[_Frame] = []
        self.root_done = False
        self.string: dict[str, Any] | None = None
        self.scalar = ""
        self.escape = False
        self.unicode = None
        self.surrogate = None

    def _path(self):
        if not self.stack:
            return ()
        frame = self.stack[-1]
        return (*frame.path, frame.key if frame.kind == "object" else frame.index)

    def _done(self):
        if self.stack:
            self.stack[-1].state = "separator"
            self.stack[-1].index += 1
        else:
            self.root_done = True

    def _character(self, char):
        assert self.string is not None
        code = ord(char)
        if self.surrogate is not None:
            if not 0xDC00 <= code <= 0xDFFF:
                raise ValueError("invalid surrogate pair")
            char = chr(0x10000 + ((self.surrogate - 0xD800) << 10) + code - 0xDC00)
            self.surrogate = None
        elif 0xD800 <= code <= 0xDBFF:
            self.surrogate = code
            return
        elif 0xDC00 <= code <= 0xDFFF:
            raise ValueError("invalid surrogate pair")
        self.string["text"] += char
        if self.string["path"] is not None:
            self.strings[self.string["path"]] = self.string["text"]

    def feed(self, delta):
        frame: _Frame | None
        for char in delta:
            if self.string is not None:
                if self.unicode is not None:
                    if char not in "0123456789abcdefABCDEF":
                        raise ValueError("invalid unicode escape")
                    self.unicode += char
                    if len(self.unicode) == 4:
                        self._character(chr(int(self.unicode, 16)))
                        self.unicode = None
                elif self.escape:
                    self.escape = False
                    if char == "u":
                        self.unicode = ""
                    else:
                        escaped = {'"': '"', "\\": "\\", "/": "/", "b": "\b", "f": "\f",
                                   "n": "\n", "r": "\r", "t": "\t"}
                        if char not in escaped:
                            raise ValueError("invalid string escape")
                        self._character(escaped[char])
                elif char == "\\":
                    self.escape = True
                elif char == '"':
                    if self.surrogate is not None:
                        raise ValueError("invalid surrogate pair")
                    path, text = self.string["path"], self.string["text"]
                    self.string = None
                    if path is None:
                        frame = self.stack[-1]
                        if text in frame.keys:
                            raise ValueError("duplicate object key")
                        frame.keys.add(text)
                        frame.key, frame.state = text, "colon"
                    else:
                        self.strings[path] = text
                        self.complete.add(path)
                        self._done()
                elif ord(char) < 0x20:
                    raise ValueError("invalid string character")
                else:
                    self._character(char)
                continue
            if self.scalar:
                if char not in " \t\n\r,]}":
                    self.scalar += char
                    continue
                json.loads(self.scalar)
                self.scalar = ""
                self._done()
            if char in " \t\n\r":
                continue
            frame = self.stack[-1] if self.stack else None
            state = frame.state if frame else "done" if self.root_done else "value"
            if state == "colon":
                assert frame is not None
                if char != ":":
                    raise ValueError("expected colon")
                frame.state = "value"
            elif state == "separator":
                assert frame is not None
                if char == ",":
                    frame.state = "key" if frame.kind == "object" else "value"
                elif char == ("}" if frame.kind == "object" else "]"):
                    self.complete.add(frame.path)
                    self.stack.pop()
                    self._done()
                else:
                    raise ValueError("expected separator")
            elif state in {"key", "key_or_end"}:
                assert frame is not None
                if char == '"':
                    self.string = {"path": None, "text": ""}
                elif char == "}" and state == "key_or_end":
                    self.complete.add(frame.path)
                    self.stack.pop()
                    self._done()
                else:
                    raise ValueError("expected object key")
            elif state in {"value", "value_or_end"}:
                if char == "]" and state == "value_or_end":
                    assert frame is not None
                    self.complete.add(frame.path)
                    self.stack.pop()
                    self._done()
                elif char in "[{":
                    self.stack.append(_Frame(self._path(), "object" if char == "{" else "array",
                                             "key_or_end" if char == "{" else "value_or_end"))
                elif char == '"':
                    self.string = {"path": self._path(), "text": ""}
                elif char in "-0123456789tfn":
                    self.scalar = char
                else:
                    raise ValueError("expected value")
            else:
                raise ValueError("unexpected content after JSON")


class AnswerStreamProjector:
    def __init__(self, mode, on_block, *, evidence_ids=(), numeric_values=None):
        self.mode = mode
        self.on_block = on_block
        self.evidence_ids = set(evidence_ids)
        self.numeric_values = numeric_values or {}
        self.decoder = _JsonStrings()
        self.published = {}
        self.invalid = False

    def _public_path(self, path):
        if self.mode == "general_only":
            return len(path) == 2 and path[0] == "paragraphs" and isinstance(path[1], int)
        return (len(path) >= 3 and path[0] in {"interpretations", "limitations"}
                and isinstance(path[1], int)
                and ((len(path) == 3 and path[2] == "text")
                     or (len(path) == 4 and path[0] == "interpretations" and path[2] == "assumptions"
                         and isinstance(path[3], int))))

    def _prefix(self, path, text):
        marker = "{{value:"
        citations: list[str] | None
        if self.mode == "general_only":
            citations = []
        else:
            citation_path = (*path[:2], "evidence_ids")
            citations = ([value for key, value in self.decoder.strings.items()
                          if key[:-1] == citation_path and key in self.decoder.complete]
                         if citation_path in self.decoder.complete else None)
        end = len(text)
        for size in range(1, len(marker)):
            if text.endswith(marker[:size]):
                end = min(end, len(text) - size)
        offset = 0
        while (start := text.find(marker, offset)) >= 0:
            close = text.find("}}", start)
            if close < 0 or citations is None:
                end = min(end, start)
                break
            try:
                fill_value_references(text[start:close + 2], citations, self.numeric_values,
                                      evidence_ids=self.evidence_ids)
            except ValueError:
                end = min(end, start)
                break
            offset = close + 2
        return fill_value_references(text[:end], citations or [], self.numeric_values,
                                     evidence_ids=self.evidence_ids)

    def feed(self, delta):
        if self.invalid:
            return
        try:
            self.decoder.feed(delta)
        except ValueError:
            # The canonical JSON/schema checks reject malformed output after the provider finishes.
            self.invalid = True
            return
        for path, text in self.decoder.strings.items():
            if not self._public_path(path):
                continue
            public = self._prefix(path, text)
            previous = self.published.get(path, "")
            if public.startswith(previous) and len(public) > len(previous):
                self.on_block(".".join(map(str, path)), public[len(previous):])
                self.published[path] = public

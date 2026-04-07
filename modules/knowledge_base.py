from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path

from config import PROJECT_ROOT, RoverConfig


TOKEN_RE = re.compile(r"[a-zA-Z0-9_]+")
TEXT_EXTENSIONS = {".md", ".txt", ".py", ".json", ".yaml", ".yml"}


@dataclass(slots=True)
class KnowledgeChunk:
    path: str
    text: str
    tokens: set[str]


class KnowledgeBase:
    def __init__(self, config: RoverConfig, root: Path = PROJECT_ROOT) -> None:
        self._config = config
        self._root = root
        self._chunks: list[KnowledgeChunk] = []
        self.refresh()

    def refresh(self) -> None:
        chunks: list[KnowledgeChunk] = []
        for path in self._iter_paths():
            if path.suffix.lower() not in TEXT_EXTENSIONS or not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore").strip()
            except Exception:
                continue
            if not text:
                continue
            relative = str(path.relative_to(self._root))
            for chunk in self._split_text(text):
                tokens = set(token.lower() for token in TOKEN_RE.findall(chunk))
                if tokens:
                    chunks.append(KnowledgeChunk(path=relative, text=chunk, tokens=tokens))
        self._chunks = chunks

    def search(self, query: str, limit: int = 4) -> list[KnowledgeChunk]:
        query_tokens = [token.lower() for token in TOKEN_RE.findall(query)]
        if not query_tokens:
            return []

        scored: list[tuple[float, KnowledgeChunk]] = []
        for chunk in self._chunks:
            overlap = sum(1 for token in query_tokens if token in chunk.tokens)
            if overlap == 0:
                continue
            score = overlap / math.sqrt(len(chunk.tokens))
            scored.append((score, chunk))

        scored.sort(key=lambda item: item[0], reverse=True)
        return [chunk for _, chunk in scored[:limit]]

    def format_context(self, query: str, limit: int = 4) -> str:
        chunks = self.search(query, limit=limit)
        if not chunks:
            return ""
        parts = []
        for chunk in chunks:
            parts.append(f"[{chunk.path}]\n{chunk.text}")
        return "\n\n".join(parts)

    def _iter_paths(self) -> list[Path]:
        paths: list[Path] = []
        for value in self._config.knowledge_paths:
            path = Path(value)
            if not path.is_absolute():
                path = self._root / path
            if path.is_file():
                paths.append(path)
            elif path.is_dir():
                paths.extend(item for item in path.rglob("*") if item.is_file())
        return paths

    @staticmethod
    def _split_text(text: str, max_chars: int = 700) -> list[str]:
        lines = [line.strip() for line in text.splitlines()]
        blocks: list[str] = []
        current: list[str] = []
        current_len = 0
        for line in lines:
            if not line:
                if current:
                    blocks.append(" ".join(current))
                    current = []
                    current_len = 0
                continue
            if current_len + len(line) > max_chars and current:
                blocks.append(" ".join(current))
                current = [line]
                current_len = len(line)
            else:
                current.append(line)
                current_len += len(line) + 1
        if current:
            blocks.append(" ".join(current))
        return blocks or [text[:max_chars]]

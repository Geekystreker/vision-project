from pathlib import Path

from config import RoverConfig
from modules.knowledge_base import KnowledgeBase


def test_knowledge_base_search_returns_relevant_chunk(tmp_path: Path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "scope.md").write_text(
        "The VISION project combines a desktop control panel, ESP32-CAM video, and follow-person autonomy.",
        encoding="utf-8",
    )
    cfg = RoverConfig("ws://cam", "ws://servo", "ws://motor", knowledge_paths=("docs",))

    kb = KnowledgeBase(cfg, root=tmp_path)
    results = kb.search("what is the scope of the VISION project")

    assert results
    assert "follow-person autonomy" in results[0].text

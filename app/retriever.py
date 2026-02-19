from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from opentelemetry import trace

TRACER = trace.get_tracer(__name__)
TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class CorpusDoc:
    id: str
    title: str
    text: str
    tags: list[str]


class OfflineRetriever:
    def __init__(self, corpus_path: Path | None = None, top_k: int | None = None) -> None:
        self._corpus_path = corpus_path or (
            Path(__file__).resolve().parent.parent / "data" / "corpus.jsonl"
        )
        self._top_k = top_k or int(os.getenv("DEMO_RETRIEVER_TOPK", "3"))
        self._docs = self._load_docs()

    def _load_docs(self) -> list[CorpusDoc]:
        docs: list[CorpusDoc] = []
        with self._corpus_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                raw = json.loads(line)
                docs.append(
                    CorpusDoc(
                        id=raw["id"],
                        title=raw["title"],
                        text=raw["text"],
                        tags=raw.get("tags", []),
                    )
                )
        return docs

    @staticmethod
    def _tokens(text: str) -> set[str]:
        return set(TOKEN_PATTERN.findall(text.lower()))

    def search(self, query: str, top_k: int | None = None) -> list[dict[str, Any]]:
        with TRACER.start_as_current_span("gen_ai.retriever") as span:
            k = top_k or self._top_k
            query_tokens = self._tokens(query)
            scored: list[tuple[int, CorpusDoc]] = []
            for doc in self._docs:
                doc_tokens = self._tokens(f"{doc.title} {doc.text} {' '.join(doc.tags)}")
                score = len(query_tokens & doc_tokens)
                if score == 0:
                    continue
                scored.append((score, doc))
            scored.sort(key=lambda item: (-item[0], item[1].id))
            selected = scored[:k]
            docs = [
                {
                    "id": doc.id,
                    "title": doc.title,
                    "text": doc.text,
                    "tags": doc.tags,
                    "score": score,
                }
                for score, doc in selected
            ]
            span.set_attribute("gen_ai.operation.name", "retrieve")
            span.set_attribute("retriever.query", query)
            span.set_attribute("retriever.top_k", k)
            span.set_attribute("retriever.result_count", len(docs))
            if docs:
                span.add_event(
                    "retriever_results",
                    {"result_ids": ",".join(d["id"] for d in docs)},
                )
            return docs

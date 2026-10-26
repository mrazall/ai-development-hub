from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod

import httpx


class EmbeddingBackend(ABC):
    model: str
    version: str

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class FakeEmbeddingBackend(EmbeddingBackend):
    def __init__(self, model: str = "fake", version: str = "1", dimensions: int = 32):
        self.model, self.version, self.dimensions = model, version, dimensions

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        for text in texts:
            digest = hashlib.sha256(text.lower().encode()).digest()
            values = [((digest[i % len(digest)] / 255.0) * 2) - 1 for i in range(self.dimensions)]
            norm = sum(v * v for v in values) ** 0.5 or 1
            vectors.append([v / norm for v in values])
        return vectors


class OllamaEmbeddingBackend(EmbeddingBackend):
    def __init__(self, base_url: str, model: str = "qwen3-embedding:0.6b", version: str = "1", batch_size: int = 16):
        self.base_url, self.model, self.version, self.batch_size = base_url.rstrip("/"), model, version, batch_size

    def embed(self, texts: list[str]) -> list[list[float]]:
        output: list[list[float]] = []
        with httpx.Client(timeout=120) as client:
            for start in range(0, len(texts), self.batch_size):
                response = client.post(
                    f"{self.base_url}/api/embed",
                    json={"model": self.model, "input": texts[start : start + self.batch_size]},
                )
                response.raise_for_status()
                data = response.json()
                # /api/embed returns "embeddings"; older /api/embeddings returned a single "embedding".
                # (A dict.get default is evaluated eagerly, so data["embedding"] there raised KeyError.)
                if "embeddings" in data:
                    output.extend(data["embeddings"])
                elif "embedding" in data:
                    output.append(data["embedding"])
                else:
                    raise ValueError("unexpected Ollama /api/embed response")
        return output

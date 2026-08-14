from __future__ import annotations

import hashlib
import math
import re
import uuid
from collections import Counter
from dataclasses import dataclass
from typing import Protocol

import httpx


@dataclass(frozen=True, slots=True)
class RetrievalDocument:
    document_id: str
    title: str
    text: str

    @property
    def searchable_text(self) -> str:
        return f"{self.title} {self.text}"


@dataclass(frozen=True, slots=True)
class RetrievalHit:
    document: RetrievalDocument
    fused_score: float
    dense_score: float
    sparse_score: float
    evidence_score: float


class EmbeddingProvider(Protocol):
    @property
    def dimension(self) -> int: ...

    def embed(self, texts: list[str]) -> list[list[float]]: ...


_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "can",
    "do",
    "does",
    "for",
    "how",
    "i",
    "in",
    "is",
    "it",
    "my",
    "of",
    "on",
    "the",
    "to",
    "what",
    "when",
    "where",
    "why",
    "with",
    "you",
}


def tokenize(text: str) -> list[str]:
    normalized = text.lower()
    english = [
        token
        for token in re.findall(r"[a-z0-9_-]+", normalized)
        if len(token) > 1 and token not in _STOPWORDS
    ]
    chinese_tokens: list[str] = []
    for segment in re.findall(r"[\u4e00-\u9fff]+", normalized):
        if len(segment) == 1:
            chinese_tokens.append(segment)
            continue
        chinese_tokens.extend(segment[index : index + 2] for index in range(len(segment) - 1))
        if len(segment) <= 8:
            chinese_tokens.append(segment)
    return english + chinese_tokens


class DeterministicHashEmbedding:
    """Deterministic vector fallback for CI/local development, not a semantic model."""

    def __init__(self, dimension: int = 192) -> None:
        self._dimension = dimension

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        for token in tokenize(text):
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=16).digest()
            first = int.from_bytes(digest[:8], "big") % self.dimension
            second = int.from_bytes(digest[8:], "big") % self.dimension
            vector[first] += 1.0
            vector[second] += 0.5
        return _normalize(vector)


class OpenAICompatibleEmbedding:
    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str | None = None,
        dimension: int | None = None,
        timeout_seconds: float = 20.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self._dimension = dimension
        self.timeout_seconds = timeout_seconds

    @property
    def dimension(self) -> int:
        if self._dimension is None:
            raise RuntimeError("embedding dimension is unknown before the first embedding call")
        return self._dimension

    def embed(self, texts: list[str]) -> list[list[float]]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        response = httpx.post(
            f"{self.base_url}/embeddings",
            headers=headers,
            json={"model": self.model, "input": texts},
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        ordered = sorted(payload["data"], key=lambda item: int(item["index"]))
        vectors = [[float(value) for value in item["embedding"]] for item in ordered]
        if len(vectors) != len(texts):
            raise RuntimeError("embedding provider returned an unexpected vector count")
        if vectors:
            dimension = len(vectors[0])
            if not dimension or any(len(vector) != dimension for vector in vectors):
                raise RuntimeError("embedding provider returned inconsistent dimensions")
            if self._dimension is not None and self._dimension != dimension:
                raise RuntimeError("embedding provider dimension changed")
            self._dimension = dimension
        return [_normalize(vector) for vector in vectors]


class BM25Retriever:
    def __init__(self, documents: list[RetrievalDocument], *, k1: float = 1.5, b: float = 0.75) -> None:
        self.documents = documents
        self.k1 = k1
        self.b = b
        self._tokens = [tokenize(document.searchable_text) for document in documents]
        self._lengths = [len(tokens) for tokens in self._tokens]
        self._avg_length = sum(self._lengths) / max(len(self._lengths), 1)
        self._document_frequency = Counter(
            token for tokens in self._tokens for token in set(tokens)
        )

    def search(self, query: str, *, limit: int) -> list[tuple[RetrievalDocument, float]]:
        query_tokens = tokenize(query)
        if not query_tokens:
            return []
        scores: list[tuple[RetrievalDocument, float]] = []
        document_count = len(self.documents)
        for document, tokens, length in zip(
            self.documents, self._tokens, self._lengths, strict=True
        ):
            frequencies = Counter(tokens)
            score = 0.0
            for token in query_tokens:
                frequency = frequencies[token]
                if not frequency:
                    continue
                df = self._document_frequency[token]
                idf = math.log(1.0 + (document_count - df + 0.5) / (df + 0.5))
                denominator = frequency + self.k1 * (
                    1.0 - self.b + self.b * length / max(self._avg_length, 1.0)
                )
                score += idf * (frequency * (self.k1 + 1.0)) / denominator
            if score > 0:
                scores.append((document, score))
        return sorted(scores, key=lambda item: item[1], reverse=True)[:limit]


class InMemoryDenseRetriever:
    def __init__(
        self,
        documents: list[RetrievalDocument],
        provider: EmbeddingProvider,
    ) -> None:
        self.documents = documents
        self.provider = provider
        self._vectors = provider.embed([document.searchable_text for document in documents])

    def search(self, query: str, *, limit: int) -> list[tuple[RetrievalDocument, float]]:
        query_vector = self.provider.embed([query])[0]
        scored = [
            (document, max(0.0, _dot(query_vector, vector)))
            for document, vector in zip(self.documents, self._vectors, strict=True)
        ]
        return sorted(scored, key=lambda item: item[1], reverse=True)[:limit]


class QdrantDenseRetriever:
    """Dense-vector adapter. Embeddings are generated by the configured provider."""

    def __init__(
        self,
        documents: list[RetrievalDocument],
        provider: EmbeddingProvider,
        *,
        url: str,
        collection: str,
        api_key: str | None = None,
    ) -> None:
        from qdrant_client import QdrantClient, models

        self.documents = {document.document_id: document for document in documents}
        self.provider = provider
        self.collection = collection
        self.client = QdrantClient(url=url, api_key=api_key)
        vectors = provider.embed([document.searchable_text for document in documents])
        dimension = len(vectors[0]) if vectors else provider.dimension
        if not self.client.collection_exists(collection):
            self.client.create_collection(
                collection_name=collection,
                vectors_config={
                    "dense": models.VectorParams(size=dimension, distance=models.Distance.COSINE)
                },
            )
        points = [
            models.PointStruct(
                id=str(uuid.uuid5(uuid.NAMESPACE_URL, document.document_id)),
                vector={"dense": vector},
                payload={"document_id": document.document_id},
            )
            for document, vector in zip(documents, vectors, strict=True)
        ]
        if points:
            self.client.upsert(collection_name=collection, points=points, wait=True)

    def search(self, query: str, *, limit: int) -> list[tuple[RetrievalDocument, float]]:
        vector = self.provider.embed([query])[0]
        response = self.client.query_points(
            collection_name=self.collection,
            query=vector,
            using="dense",
            limit=limit,
            with_payload=True,
        )
        results: list[tuple[RetrievalDocument, float]] = []
        for point in response.points:
            payload = point.payload or {}
            document_id = str(payload.get("document_id", ""))
            document = self.documents.get(document_id)
            if document is not None:
                results.append((document, max(0.0, float(point.score))))
        return results


class HybridRetriever:
    def __init__(
        self,
        documents: list[RetrievalDocument],
        *,
        dense_retriever: InMemoryDenseRetriever | QdrantDenseRetriever,
        sparse_retriever: BM25Retriever | None = None,
        rrf_k: int = 60,
    ) -> None:
        self.documents = documents
        self.dense = dense_retriever
        self.sparse = sparse_retriever or BM25Retriever(documents)
        self.rrf_k = rrf_k

    def search(self, query: str, *, limit: int = 3, prefetch: int = 10) -> list[RetrievalHit]:
        dense = self.dense.search(query, limit=prefetch)
        sparse = self.sparse.search(query, limit=prefetch)
        dense_rank = {document.document_id: rank for rank, (document, _) in enumerate(dense, 1)}
        sparse_rank = {document.document_id: rank for rank, (document, _) in enumerate(sparse, 1)}
        dense_score = {document.document_id: score for document, score in dense}
        sparse_score = {document.document_id: score for document, score in sparse}

        candidates = set(dense_rank) | set(sparse_rank)
        hits: list[RetrievalHit] = []
        query_tokens = set(tokenize(query))
        by_id = {document.document_id: document for document in self.documents}
        for document_id in candidates:
            document = by_id[document_id]
            fused = 0.0
            if document_id in dense_rank:
                fused += 1.0 / (self.rrf_k + dense_rank[document_id])
            if document_id in sparse_rank:
                fused += 1.0 / (self.rrf_k + sparse_rank[document_id])

            sparse_raw = sparse_score.get(document_id, 0.0)
            dense_raw = dense_score.get(document_id, 0.0)
            document_tokens = set(tokenize(document.searchable_text))
            coverage = len(query_tokens & document_tokens) / max(len(query_tokens), 1)
            sparse_normalized = sparse_raw / (1.0 + sparse_raw)
            evidence = min(
                1.0,
                0.45 * dense_raw + 0.35 * sparse_normalized + 0.20 * coverage,
            )
            hits.append(
                RetrievalHit(
                    document=document,
                    fused_score=round(fused, 6),
                    dense_score=round(dense_raw, 6),
                    sparse_score=round(sparse_raw, 6),
                    evidence_score=round(evidence, 6),
                )
            )

        return sorted(
            hits,
            key=lambda item: (item.fused_score, item.evidence_score),
            reverse=True,
        )[:limit]


def _normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if not norm:
        return vector
    return [value / norm for value in vector]


def _dot(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        raise ValueError("vectors must have the same dimension")
    return sum(a * b for a, b in zip(left, right, strict=True))

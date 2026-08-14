from app.config import Settings
from app.container import build_container
from app.knowledge import KnowledgeService
from app.retrieval import DeterministicHashEmbedding


def test_hybrid_retrieval_prefers_shipping_evidence():
    service = KnowledgeService()
    citations = service.search("where can I find package tracking after shipment")
    assert citations
    assert citations[0].document_id == "KB-SHIPPING-01"
    assert citations[0].score >= service.min_evidence_score


def test_unsupported_query_abstains_instead_of_hallucinating_evidence():
    service = KnowledgeService()
    assert service.search("explain quantum entanglement in detail") == []


def test_deterministic_grounded_answer_keeps_source_id():
    service = KnowledgeService()
    citations = service.search("怎么取消订阅自动续费？")
    answer = service.answer("怎么取消订阅自动续费？", citations)
    assert citations
    assert f"[{citations[0].document_id}]" in answer


def test_deterministic_embedding_is_stable_and_normalized():
    provider = DeterministicHashEmbedding(dimension=64)
    first = provider.embed(["refund policy"])[0]
    second = provider.embed(["refund policy"])[0]
    assert first == second
    assert len(first) == 64
    assert abs(sum(value * value for value in first) - 1.0) < 1e-9


def test_qdrant_backend_rejects_ci_only_embedding(tmp_path):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'supportops.db'}",
        knowledge_backend="qdrant",
        embedding_backend="deterministic",
    )
    try:
        build_container(settings)
    except ValueError as exc:
        assert "requires EMBEDDING_BACKEND=openai" in str(exc)
    else:
        raise AssertionError("qdrant backend accepted deterministic CI embedding")

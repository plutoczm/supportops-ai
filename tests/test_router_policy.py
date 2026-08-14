from app.domain import Intent, PolicyAction
from app.knowledge import KnowledgeService
from app.policy import ActionPolicy
from app.router import IntentRouter


def test_policy_questions_do_not_become_refund_actions():
    router = IntentRouter()
    assert router.route("退款政策怎么规定？").intent is Intent.KNOWLEDGE
    assert router.route("我要退款 ORD-1001").intent is Intent.REFUND


def test_mutating_policy_never_auto_allows():
    policy = ActionPolicy(refund_human_review_threshold=500)
    assert policy.refund(199).action is PolicyAction.REQUIRE_CONFIRMATION
    assert policy.refund(899).action is PolicyAction.REQUIRE_HUMAN
    assert policy.return_request().action is PolicyAction.REQUIRE_CONFIRMATION


def test_knowledge_returns_evidence():
    service = KnowledgeService()
    hits = service.search("退款政策")
    assert hits
    assert hits[0].document_id.startswith("KB-")

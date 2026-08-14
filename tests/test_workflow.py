from app.config import Settings
from app.container import build_container
from app.domain import PendingActionStatus, SupportRequest


def build_test_container(tmp_path):
    return build_container(Settings(database_url=f"sqlite:///{tmp_path / 'supportops.db'}"))


def test_refund_requires_confirmation_and_is_idempotent(tmp_path):
    container = build_test_container(tmp_path)
    response = container.orchestrator.handle(
        SupportRequest(
            conversation_id="CONV-1",
            customer_id="CUST-001",
            message="我要退款 ORD-1001",
        )
    )
    assert response.pending_action_id is not None
    assert response.handoff is False
    before = container.store.get_order("ORD-1001", "CUST-001")
    assert before is not None
    assert before.refund_status == "none"

    first = container.orchestrator.confirm(response.pending_action_id, "CUST-001")
    second = container.orchestrator.confirm(response.pending_action_id, "CUST-001")
    assert first.status is PendingActionStatus.EXECUTED
    assert first.result == second.result
    assert first.result["refund_status"] == "requested"


def test_high_value_refund_requires_human_review(tmp_path):
    container = build_test_container(tmp_path)
    response = container.orchestrator.handle(
        SupportRequest(
            conversation_id="CONV-2",
            customer_id="CUST-002",
            message="退款 ORD-2001",
        )
    )
    assert response.handoff is True
    assert response.ticket_id is not None
    assert response.pending_action_id is None


def test_cross_customer_order_is_not_disclosed(tmp_path):
    container = build_test_container(tmp_path)
    response = container.orchestrator.handle(
        SupportRequest(
            conversation_id="CONV-3",
            customer_id="CUST-001",
            message="订单状态 ORD-2001",
        )
    )
    assert "未找到" in response.answer
    assert "delivered" not in response.answer


def test_return_requires_confirmation(tmp_path):
    container = build_test_container(tmp_path)
    response = container.orchestrator.handle(
        SupportRequest(
            conversation_id="CONV-4",
            customer_id="CUST-001",
            message="退货 ORD-1001",
        )
    )
    assert response.pending_action_id is not None
    result = container.orchestrator.confirm(response.pending_action_id, "CUST-001")
    assert result.result["return_status"] == "requested"

from fastapi.testclient import TestClient

from app.config import Settings
from app.container import build_container
from app.main import create_app


def test_api_refund_confirmation_flow(tmp_path):
    container = build_container(Settings(database_url=f"sqlite:///{tmp_path / 'api.db'}"))
    client = TestClient(create_app(container))

    response = client.post(
        "/v1/support/messages",
        json={
            "conversation_id": "CONV-API",
            "customer_id": "CUST-001",
            "message": "退款 ORD-1001",
        },
    )
    assert response.status_code == 200
    action_id = response.json()["pending_action_id"]
    assert action_id

    confirm = client.post(
        f"/v1/actions/{action_id}/confirm",
        json={"customer_id": "CUST-001"},
    )
    assert confirm.status_code == 200
    assert confirm.json()["result"]["refund_status"] == "requested"


def test_api_prevents_cross_customer_order_read(tmp_path):
    container = build_container(Settings(database_url=f"sqlite:///{tmp_path / 'api2.db'}"))
    client = TestClient(create_app(container))
    response = client.get("/v1/orders/ORD-2001", params={"customer_id": "CUST-001"})
    assert response.status_code == 404

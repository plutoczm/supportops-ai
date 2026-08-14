from __future__ import annotations

import re
from uuid import uuid4

from app.domain import (
    ConfirmationResponse,
    Intent,
    PendingActionKind,
    PendingActionStatus,
    PolicyAction,
    SupportRequest,
    SupportResponse,
)
from app.guardrails import InputGuardrails
from app.knowledge import KnowledgeService
from app.policy import ActionPolicy
from app.router import IntentRouter
from app.store import SupportStore
from app.tools import SupportTools


class SupportOrchestrator:
    def __init__(
        self,
        *,
        store: SupportStore,
        guardrails: InputGuardrails,
        router: IntentRouter,
        knowledge: KnowledgeService,
        policy: ActionPolicy,
        tools: SupportTools,
    ) -> None:
        self.store = store
        self.guardrails = guardrails
        self.router = router
        self.knowledge = knowledge
        self.policy = policy
        self.tools = tools

    def handle(self, request: SupportRequest) -> SupportResponse:
        trace_id = self._trace_id()
        safety = self.guardrails.inspect(request.message)
        if safety.blocked:
            return SupportResponse(
                trace_id=trace_id,
                intent=Intent.UNKNOWN,
                answer="该请求包含试图绕过系统安全边界的指令，未调用模型或业务工具。",
                safety_labels=safety.labels,
            )

        safe_message = safety.sanitized_text
        route = self.router.route(safe_message)
        if route.intent is Intent.KNOWLEDGE:
            citations = self.knowledge.search(safe_message)
            return SupportResponse(
                trace_id=trace_id,
                intent=route.intent,
                answer=self.knowledge.answer(safe_message, citations),
                citations=citations,
                safety_labels=safety.labels,
            )
        if route.intent is Intent.ORDER_STATUS:
            return self._order_status(
                customer_id=request.customer_id,
                message=safe_message,
                intent=route.intent,
                trace_id=trace_id,
                safety_labels=safety.labels,
            )
        if route.intent is Intent.REFUND:
            order_id = self._extract_order_id(safe_message)
            if order_id is None:
                return self._missing_order_id(route.intent, trace_id, safety.labels)
            return self.prepare_refund(
                customer_id=request.customer_id,
                conversation_id=request.conversation_id,
                order_id=order_id,
                trace_id=trace_id,
                safety_labels=safety.labels,
            )
        if route.intent is Intent.RETURN_REQUEST:
            return self._prepare_return(
                customer_id=request.customer_id,
                conversation_id=request.conversation_id,
                message=safe_message,
                trace_id=trace_id,
                safety_labels=safety.labels,
            )
        if route.intent is Intent.COMPLAINT:
            ticket = self.tools.create_ticket(
                customer_id=request.customer_id,
                conversation_id=request.conversation_id,
                reason=safe_message,
            )
            return SupportResponse(
                trace_id=trace_id,
                intent=route.intent,
                answer="已创建客服工单并转人工处理。",
                ticket_id=ticket.ticket_id,
                handoff=True,
                safety_labels=safety.labels,
            )

        ticket = self.tools.create_ticket(
            customer_id=request.customer_id,
            conversation_id=request.conversation_id,
            reason=f"unresolved_request: {safe_message}",
        )
        return SupportResponse(
            trace_id=trace_id,
            intent=Intent.UNKNOWN,
            answer="当前自动化流程无法可靠处理该请求，已转人工客服。",
            ticket_id=ticket.ticket_id,
            handoff=True,
            safety_labels=safety.labels,
        )

    def prepare_refund(
        self,
        *,
        customer_id: str,
        conversation_id: str,
        order_id: str,
        trace_id: str | None = None,
        safety_labels: list[str] | None = None,
    ) -> SupportResponse:
        trace_id = trace_id or self._trace_id()
        labels = safety_labels or []
        try:
            quote = self.tools.quote_refund(order_id=order_id, customer_id=customer_id)
        except ValueError as exc:
            return SupportResponse(
                trace_id=trace_id,
                intent=Intent.REFUND,
                answer=f"无法创建退款请求：{exc}。",
                safety_labels=labels,
            )

        amount = float(quote["amount"])
        decision = self.policy.refund(amount)
        if decision.action is PolicyAction.REQUIRE_HUMAN:
            ticket = self.tools.create_ticket(
                customer_id=customer_id,
                conversation_id=conversation_id,
                reason=f"high_value_refund:{order_id}:{amount}",
            )
            return SupportResponse(
                trace_id=trace_id,
                intent=Intent.REFUND,
                answer=f"该订单预计可退 {amount:.2f}，金额超过自动处理阈值，已转人工审核。",
                ticket_id=ticket.ticket_id,
                handoff=True,
                safety_labels=labels,
            )

        pending = self.store.create_pending_action(
            conversation_id=conversation_id,
            customer_id=customer_id,
            kind=PendingActionKind.REFUND,
            payload={"order_id": order_id, "amount": amount},
        )
        return SupportResponse(
            trace_id=trace_id,
            intent=Intent.REFUND,
            answer=f"订单 {order_id} 预计可退 {amount:.2f}。需要你明确确认后才会提交退款。",
            pending_action_id=pending.action_id,
            safety_labels=labels,
        )

    def confirm(self, action_id: str, customer_id: str) -> ConfirmationResponse:
        trace_id = self._trace_id()
        pending = self.store.get_pending_action(action_id)
        if pending is None:
            raise ValueError("pending_action_not_found")
        if pending.customer_id != customer_id:
            raise PermissionError("pending_action_customer_mismatch")
        if pending.status is PendingActionStatus.EXECUTED:
            return ConfirmationResponse(
                trace_id=trace_id,
                action_id=action_id,
                status=pending.status,
                result=pending.result or {},
            )

        order_id = str(pending.payload["order_id"])
        if pending.kind is PendingActionKind.REFUND:
            result = self.tools.execute_refund(
                order_id=order_id,
                customer_id=customer_id,
                idempotency_key=action_id,
            )
        elif pending.kind is PendingActionKind.RETURN_REQUEST:
            result = self.tools.execute_return(
                order_id=order_id,
                customer_id=customer_id,
                idempotency_key=action_id,
            )
        else:
            raise ValueError("unsupported_pending_action")

        self.store.mark_action_executed(action_id, result)
        return ConfirmationResponse(
            trace_id=trace_id,
            action_id=action_id,
            status=PendingActionStatus.EXECUTED,
            result=result,
        )

    def _order_status(
        self,
        *,
        customer_id: str,
        message: str,
        intent: Intent,
        trace_id: str,
        safety_labels: list[str],
    ) -> SupportResponse:
        order_id = self._extract_order_id(message)
        if order_id is None:
            return self._missing_order_id(intent, trace_id, safety_labels)
        order = self.tools.get_order(order_id=order_id, customer_id=customer_id)
        if order is None:
            return SupportResponse(
                trace_id=trace_id,
                intent=intent,
                answer="未找到属于当前客户的订单，未暴露其他客户的订单信息。",
                safety_labels=safety_labels,
            )
        return SupportResponse(
            trace_id=trace_id,
            intent=intent,
            answer=f"订单 {order.order_id} 当前状态：{order.status}。",
            safety_labels=safety_labels,
        )

    def _prepare_return(
        self,
        *,
        customer_id: str,
        conversation_id: str,
        message: str,
        trace_id: str,
        safety_labels: list[str],
    ) -> SupportResponse:
        order_id = self._extract_order_id(message)
        if order_id is None:
            return self._missing_order_id(Intent.RETURN_REQUEST, trace_id, safety_labels)
        order = self.tools.get_order(order_id=order_id, customer_id=customer_id)
        if order is None or order.status != "delivered":
            return SupportResponse(
                trace_id=trace_id,
                intent=Intent.RETURN_REQUEST,
                answer="该订单当前不能自动创建退货申请，建议转人工客服核验。",
                handoff=True,
                safety_labels=safety_labels,
            )
        decision = self.policy.return_request()
        if decision.action is not PolicyAction.REQUIRE_CONFIRMATION:
            raise RuntimeError("return_policy_must_require_confirmation")
        pending = self.store.create_pending_action(
            conversation_id=conversation_id,
            customer_id=customer_id,
            kind=PendingActionKind.RETURN_REQUEST,
            payload={"order_id": order_id},
        )
        return SupportResponse(
            trace_id=trace_id,
            intent=Intent.RETURN_REQUEST,
            answer=f"订单 {order_id} 可以申请退货，需要你明确确认后才会提交。",
            pending_action_id=pending.action_id,
            safety_labels=safety_labels,
        )

    @staticmethod
    def _extract_order_id(text: str) -> str | None:
        match = re.search(r"\bORD-\d{4,}\b", text.upper())
        return match.group(0) if match else None

    @staticmethod
    def _missing_order_id(
        intent: Intent,
        trace_id: str,
        safety_labels: list[str],
    ) -> SupportResponse:
        return SupportResponse(
            trace_id=trace_id,
            intent=intent,
            answer="请提供订单号（例如 ORD-1001），系统不会猜测或查询其他客户订单。",
            safety_labels=safety_labels,
        )

    @staticmethod
    def _trace_id() -> str:
        return f"TRC-{uuid4().hex[:16]}"

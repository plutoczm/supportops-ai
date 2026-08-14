from __future__ import annotations

import re
from datetime import UTC, datetime
from uuid import uuid4

from app.auth import Principal
from app.domain import (
    ConfirmationResponse,
    Intent,
    PendingActionKind,
    PendingActionStatus,
    PendingActionView,
    PolicyAction,
    SupportRequest,
    SupportResponse,
    TicketPriority,
)
from app.guardrails import InputGuardrails
from app.knowledge import KnowledgeService
from app.policy import ActionPolicy
from app.reliability import (
    LocalReliabilityCoordinator,
    MutationLockBusy,
    RedisReliabilityCoordinator,
    ReliabilityBackendError,
)
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
        reliability: LocalReliabilityCoordinator | RedisReliabilityCoordinator,
        action_confirmation_ttl_seconds: int,
        action_lock_ttl_seconds: int,
        fail_closed_mutations: bool,
    ) -> None:
        self.store = store
        self.guardrails = guardrails
        self.router = router
        self.knowledge = knowledge
        self.policy = policy
        self.tools = tools
        self.reliability = reliability
        self.action_confirmation_ttl_seconds = max(1, action_confirmation_ttl_seconds)
        self.action_lock_ttl_seconds = max(1, action_lock_ttl_seconds)
        self.fail_closed_mutations = fail_closed_mutations

    def handle(self, request: SupportRequest, principal: Principal) -> SupportResponse:
        trace_id = self._trace_id()
        customer_id = principal.require_customer()
        safety = self.guardrails.inspect(request.message)
        if safety.blocked:
            self.store.record_audit(
                trace_id=trace_id,
                actor_id=principal.subject,
                operation="guardrail.inspect",
                resource_type="conversation",
                resource_id=request.conversation_id,
                outcome="blocked",
                details={"labels": safety.labels},
            )
            return SupportResponse(
                trace_id=trace_id,
                intent=Intent.UNKNOWN,
                answer="该请求包含试图绕过系统安全边界的指令，未调用模型或业务工具。",
                safety_labels=safety.labels,
            )

        safe_message = safety.sanitized_text
        route = self.router.route(safe_message)
        self.store.record_audit(
            trace_id=trace_id,
            actor_id=principal.subject,
            operation="agent.route",
            resource_type="conversation",
            resource_id=request.conversation_id,
            outcome="success",
            details={
                "intent": route.intent.value,
                "confidence": route.confidence,
                "source": route.source,
            },
        )

        if route.intent is Intent.KNOWLEDGE:
            search = self.knowledge.search_with_status(safe_message)
            citations = search.citations
            self.store.record_audit(
                trace_id=trace_id,
                actor_id=principal.subject,
                operation="knowledge.search",
                resource_type="knowledge",
                resource_id=None,
                outcome="degraded" if search.degraded else "success",
                details={
                    "citation_count": len(citations),
                    "degraded": search.degraded,
                    "degradation_reason": search.degradation_reason,
                    "chunk_ids": [citation.chunk_id for citation in citations],
                    "document_versions": [
                        citation.document_version for citation in citations
                    ],
                },
            )
            return SupportResponse(
                trace_id=trace_id,
                intent=route.intent,
                answer=self.knowledge.answer(safe_message, citations),
                citations=citations,
                safety_labels=safety.labels,
                retrieval_degraded=search.degraded,
                retrieval_degradation_reason=search.degradation_reason,
            )
        if route.intent is Intent.ORDER_STATUS:
            return self._order_status(
                customer_id=customer_id,
                actor_id=principal.subject,
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
                customer_id=customer_id,
                actor_id=principal.subject,
                conversation_id=request.conversation_id,
                order_id=order_id,
                trace_id=trace_id,
                safety_labels=safety.labels,
            )
        if route.intent is Intent.RETURN_REQUEST:
            return self._prepare_return(
                customer_id=customer_id,
                actor_id=principal.subject,
                conversation_id=request.conversation_id,
                message=safe_message,
                trace_id=trace_id,
                safety_labels=safety.labels,
            )
        if route.intent is Intent.COMPLAINT:
            ticket = self.tools.create_ticket(
                customer_id=customer_id,
                conversation_id=request.conversation_id,
                reason=safe_message,
                trace_id=trace_id,
                actor_id=principal.subject,
                priority=TicketPriority.NORMAL,
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
            customer_id=customer_id,
            conversation_id=request.conversation_id,
            reason=f"unresolved_request: {safe_message}",
            trace_id=trace_id,
            actor_id=principal.subject,
            priority=TicketPriority.LOW,
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
        actor_id: str,
        conversation_id: str,
        order_id: str,
        trace_id: str | None = None,
        safety_labels: list[str] | None = None,
    ) -> SupportResponse:
        trace_id = trace_id or self._trace_id()
        labels = safety_labels or []
        try:
            quote = self.tools.quote_refund(
                order_id=order_id,
                customer_id=customer_id,
                trace_id=trace_id,
                actor_id=actor_id,
            )
        except ValueError as exc:
            return SupportResponse(
                trace_id=trace_id,
                intent=Intent.REFUND,
                answer=f"无法创建退款请求：{exc}。",
                safety_labels=labels,
            )

        amount = float(quote["amount"])
        decision = self.policy.refund(amount)
        self.store.record_audit(
            trace_id=trace_id,
            actor_id=actor_id,
            operation="policy.refund",
            resource_type="order",
            resource_id=order_id,
            outcome=decision.action.value,
            details={"amount": amount, "reasons": decision.reasons},
        )
        if decision.action is PolicyAction.REQUIRE_HUMAN:
            ticket = self.tools.create_ticket(
                customer_id=customer_id,
                conversation_id=conversation_id,
                reason=f"high_value_refund:{order_id}:{amount}",
                trace_id=trace_id,
                actor_id=actor_id,
                priority=TicketPriority.HIGH,
            )
            return SupportResponse(
                trace_id=trace_id,
                intent=Intent.REFUND,
                answer=f"该订单预计可退 {amount:.2f}，金额超过自动处理阈值，已转人工审核。",
                ticket_id=ticket.ticket_id,
                handoff=True,
                safety_labels=labels,
            )

        pending = self._create_pending_action(
            conversation_id=conversation_id,
            customer_id=customer_id,
            kind=PendingActionKind.REFUND,
            payload={"order_id": order_id, "amount": amount},
            trace_id=trace_id,
            actor_id=actor_id,
        )
        return SupportResponse(
            trace_id=trace_id,
            intent=Intent.REFUND,
            answer=(
                f"订单 {order_id} 预计可退 {amount:.2f}。需要你在有效期内明确确认后才会提交退款。"
            ),
            pending_action_id=pending.action_id,
            pending_action_expires_at=pending.expires_at,
            safety_labels=labels,
        )

    def resolve_action(
        self,
        action_id: str,
        principal: Principal,
        *,
        confirm: bool,
    ) -> ConfirmationResponse:
        trace_id = self._trace_id()
        customer_id = principal.require_customer()
        pending = self.store.get_pending_action(action_id)
        if pending is None:
            raise ValueError("pending_action_not_found")
        if pending.customer_id != customer_id:
            raise PermissionError("pending_action_customer_mismatch")
        if pending.status in {
            PendingActionStatus.EXECUTED,
            PendingActionStatus.CANCELLED,
            PendingActionStatus.EXPIRED,
        }:
            return self._terminal_response(trace_id, pending)

        token: str | None = None
        lock_bypassed = False
        try:
            try:
                token = self.reliability.acquire_action_lock(
                    action_id,
                    self.action_lock_ttl_seconds,
                )
            except ReliabilityBackendError as exc:
                self.store.record_audit(
                    trace_id=trace_id,
                    actor_id=principal.subject,
                    operation="reliability.action_lock",
                    resource_type="pending_action",
                    resource_id=action_id,
                    outcome="unavailable",
                    details={"reason": exc.reason, "operation": exc.operation},
                )
                if self.fail_closed_mutations:
                    raise
                lock_bypassed = True

            if token is None and not lock_bypassed:
                raise MutationLockBusy("action_resolution_in_progress")

            pending = self.store.get_pending_action(action_id)
            if pending is None:
                raise ValueError("pending_action_not_found")
            if pending.status in {
                PendingActionStatus.EXECUTED,
                PendingActionStatus.CANCELLED,
                PendingActionStatus.EXPIRED,
            }:
                return self._terminal_response(trace_id, pending)
            if pending.expires_at <= datetime.now(UTC):
                return self._expire_action(trace_id, principal.subject, pending)

            remaining_ttl = max(
                1,
                int((pending.expires_at - datetime.now(UTC)).total_seconds()),
            )
            try:
                self.reliability.register_action_ttl(action_id, remaining_ttl)
            except ReliabilityBackendError as exc:
                self.store.record_audit(
                    trace_id=trace_id,
                    actor_id=principal.subject,
                    operation="reliability.action_ttl",
                    resource_type="pending_action",
                    resource_id=action_id,
                    outcome="unavailable",
                    details={"reason": exc.reason, "operation": exc.operation},
                )
                if self.fail_closed_mutations:
                    raise

            if not confirm:
                self.store.mark_action_cancelled(action_id)
                self._clear_action_ttl(action_id, trace_id, principal.subject)
                self.store.record_audit(
                    trace_id=trace_id,
                    actor_id=principal.subject,
                    operation="action.cancel",
                    resource_type="pending_action",
                    resource_id=action_id,
                    outcome="success",
                    details={"kind": pending.kind.value},
                )
                return ConfirmationResponse(
                    trace_id=trace_id,
                    action_id=action_id,
                    status=PendingActionStatus.CANCELLED,
                    result={"cancelled": True},
                )

            order_id = str(pending.payload["order_id"])
            if pending.kind is PendingActionKind.REFUND:
                result = self.tools.execute_refund(
                    order_id=order_id,
                    customer_id=customer_id,
                    idempotency_key=action_id,
                    trace_id=trace_id,
                    actor_id=principal.subject,
                )
            elif pending.kind is PendingActionKind.RETURN_REQUEST:
                result = self.tools.execute_return(
                    order_id=order_id,
                    customer_id=customer_id,
                    idempotency_key=action_id,
                    trace_id=trace_id,
                    actor_id=principal.subject,
                )
            else:
                raise ValueError("unsupported_pending_action")

            self.store.mark_action_executed(action_id, result)
            self._clear_action_ttl(action_id, trace_id, principal.subject)
            return ConfirmationResponse(
                trace_id=trace_id,
                action_id=action_id,
                status=PendingActionStatus.EXECUTED,
                result=result,
            )
        finally:
            if token is not None:
                try:
                    self.reliability.release_action_lock(action_id, token)
                except ReliabilityBackendError as exc:
                    self.store.record_audit(
                        trace_id=trace_id,
                        actor_id=principal.subject,
                        operation="reliability.action_lock.release",
                        resource_type="pending_action",
                        resource_id=action_id,
                        outcome="degraded",
                        details={"reason": exc.reason, "operation": exc.operation},
                    )

    def _order_status(
        self,
        *,
        customer_id: str,
        actor_id: str,
        message: str,
        intent: Intent,
        trace_id: str,
        safety_labels: list[str],
    ) -> SupportResponse:
        order_id = self._extract_order_id(message)
        if order_id is None:
            return self._missing_order_id(intent, trace_id, safety_labels)
        order = self.tools.get_order(
            order_id=order_id,
            customer_id=customer_id,
            trace_id=trace_id,
            actor_id=actor_id,
        )
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
        actor_id: str,
        conversation_id: str,
        message: str,
        trace_id: str,
        safety_labels: list[str],
    ) -> SupportResponse:
        order_id = self._extract_order_id(message)
        if order_id is None:
            return self._missing_order_id(Intent.RETURN_REQUEST, trace_id, safety_labels)
        order = self.tools.get_order(
            order_id=order_id,
            customer_id=customer_id,
            trace_id=trace_id,
            actor_id=actor_id,
        )
        if order is None or order.status != "delivered":
            ticket = self.tools.create_ticket(
                customer_id=customer_id,
                conversation_id=conversation_id,
                reason=f"return_review:{order_id}",
                trace_id=trace_id,
                actor_id=actor_id,
                priority=TicketPriority.NORMAL,
            )
            return SupportResponse(
                trace_id=trace_id,
                intent=Intent.RETURN_REQUEST,
                answer="该订单当前不能自动创建退货申请，已转人工客服核验。",
                ticket_id=ticket.ticket_id,
                handoff=True,
                safety_labels=safety_labels,
            )
        decision = self.policy.return_request()
        if decision.action is not PolicyAction.REQUIRE_CONFIRMATION:
            raise RuntimeError("return_policy_must_require_confirmation")
        pending = self._create_pending_action(
            conversation_id=conversation_id,
            customer_id=customer_id,
            kind=PendingActionKind.RETURN_REQUEST,
            payload={"order_id": order_id},
            trace_id=trace_id,
            actor_id=actor_id,
        )
        return SupportResponse(
            trace_id=trace_id,
            intent=Intent.RETURN_REQUEST,
            answer=f"订单 {order_id} 可以申请退货，需要你在有效期内明确确认后才会提交。",
            pending_action_id=pending.action_id,
            pending_action_expires_at=pending.expires_at,
            safety_labels=safety_labels,
        )

    def _create_pending_action(
        self,
        *,
        conversation_id: str,
        customer_id: str,
        kind: PendingActionKind,
        payload: dict[str, object],
        trace_id: str,
        actor_id: str,
    ) -> PendingActionView:
        pending = self.store.create_pending_action(
            conversation_id=conversation_id,
            customer_id=customer_id,
            kind=kind,
            payload=dict(payload),
            ttl_seconds=self.action_confirmation_ttl_seconds,
        )
        try:
            self.reliability.register_action_ttl(
                pending.action_id,
                self.action_confirmation_ttl_seconds,
            )
            ttl_outcome = "registered"
        except ReliabilityBackendError as exc:
            ttl_outcome = "degraded"
            self.store.record_audit(
                trace_id=trace_id,
                actor_id=actor_id,
                operation="reliability.action_ttl",
                resource_type="pending_action",
                resource_id=pending.action_id,
                outcome="degraded",
                details={"reason": exc.reason, "operation": exc.operation},
            )
        self.store.record_audit(
            trace_id=trace_id,
            actor_id=actor_id,
            operation="action.prepare",
            resource_type="pending_action",
            resource_id=pending.action_id,
            outcome="confirmation_required",
            details={
                "kind": pending.kind.value,
                "expires_at": pending.expires_at.isoformat(),
                "ttl_backend": ttl_outcome,
            },
        )
        return pending

    def _expire_action(
        self,
        trace_id: str,
        actor_id: str,
        pending: PendingActionView,
    ) -> ConfirmationResponse:
        self.store.mark_action_expired(pending.action_id)
        self._clear_action_ttl(pending.action_id, trace_id, actor_id)
        self.store.record_audit(
            trace_id=trace_id,
            actor_id=actor_id,
            operation="action.expire",
            resource_type="pending_action",
            resource_id=pending.action_id,
            outcome="expired",
            details={"kind": pending.kind.value, "expires_at": pending.expires_at.isoformat()},
        )
        return ConfirmationResponse(
            trace_id=trace_id,
            action_id=pending.action_id,
            status=PendingActionStatus.EXPIRED,
            result={"expired": True},
        )

    def _clear_action_ttl(self, action_id: str, trace_id: str, actor_id: str) -> None:
        try:
            self.reliability.clear_action_ttl(action_id)
        except ReliabilityBackendError as exc:
            self.store.record_audit(
                trace_id=trace_id,
                actor_id=actor_id,
                operation="reliability.action_ttl.clear",
                resource_type="pending_action",
                resource_id=action_id,
                outcome="degraded",
                details={"reason": exc.reason, "operation": exc.operation},
            )

    @staticmethod
    def _terminal_response(trace_id: str, pending: PendingActionView) -> ConfirmationResponse:
        return ConfirmationResponse(
            trace_id=trace_id,
            action_id=pending.action_id,
            status=pending.status,
            result=pending.result or {},
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

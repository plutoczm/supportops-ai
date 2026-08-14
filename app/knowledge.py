from __future__ import annotations

import re
from dataclasses import dataclass

from app.domain import KnowledgeCitation
from app.model_gateway import ModelGatewayError, OpenAICompatibleModel


@dataclass(frozen=True, slots=True)
class KnowledgeDocument:
    document_id: str
    title: str
    text: str


class KnowledgeService:
    """Grounded knowledge service with a deterministic local retrieval baseline."""

    def __init__(self, model: OpenAICompatibleModel | None = None) -> None:
        self.model = model
        self.documents = [
            KnowledgeDocument(
                "KB-REFUND-01",
                "退款政策",
                "已签收订单若商品符合售后条件，可申请退款。退款执行前必须由用户确认；"
                "高金额退款需要人工客服审核。",
            ),
            KnowledgeDocument(
                "KB-SHIPPING-01",
                "物流政策",
                "已发货订单可查询物流状态。运输中的订单不能直接发起已签收商品的退货流程。",
            ),
            KnowledgeDocument(
                "KB-RETURN-01",
                "退货政策",
                "已签收订单可以申请退货。系统先创建待确认动作，用户确认后才提交退货申请。",
            ),
            KnowledgeDocument(
                "KB-COUPON-01",
                "优惠券说明",
                "优惠券能否使用取决于有效期、适用商品范围和订单门槛；系统不会绕过营销规则。",
            ),
        ]

    def search(self, query: str, limit: int = 3) -> list[KnowledgeCitation]:
        query_tokens = self._tokens(query)
        scored: list[KnowledgeCitation] = []
        for document in self.documents:
            document_tokens = self._tokens(f"{document.title} {document.text}")
            overlap = len(query_tokens & document_tokens)
            if overlap == 0:
                continue
            score = overlap / max(len(query_tokens), 1)
            scored.append(
                KnowledgeCitation(
                    document_id=document.document_id,
                    title=document.title,
                    snippet=document.text,
                    score=round(score, 4),
                )
            )
        return sorted(scored, key=lambda item: item.score, reverse=True)[:limit]

    def answer(self, query: str, citations: list[KnowledgeCitation]) -> str:
        if not citations:
            return "当前知识库没有足够证据回答这个问题，建议转人工客服处理。"
        if self.model is None:
            return citations[0].snippet

        evidence = "\n".join(
            f"[{item.document_id}] {item.title}: {item.snippet}" for item in citations
        )
        system = (
            "You are a customer-support answer composer. Answer only from the supplied evidence. "
            "Do not invent policies, order state, refunds, or actions. If evidence is insufficient, "
            "say that human support is required. Keep source ids such as [KB-...] in the answer."
        )
        user = f"Question:\n{query}\n\nEvidence:\n{evidence}"
        try:
            return self.model.chat_text(system=system, user=user)
        except ModelGatewayError:
            return citations[0].snippet

    @staticmethod
    def _tokens(text: str) -> set[str]:
        english = re.findall(r"[a-z0-9_-]+", text.lower())
        chinese = [char for char in text if "\u4e00" <= char <= "\u9fff"]
        return set(english + chinese)

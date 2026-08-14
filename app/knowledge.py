from __future__ import annotations

from app.domain import KnowledgeCitation
from app.model_gateway import ModelGatewayError, OpenAICompatibleModel
from app.retrieval import (
    BM25Retriever,
    DeterministicHashEmbedding,
    HybridRetriever,
    InMemoryDenseRetriever,
    RetrievalDocument,
)


def default_knowledge_documents() -> list[RetrievalDocument]:
    return [
        RetrievalDocument(
            "KB-REFUND-01",
            "退款政策 Refund policy",
            "已签收订单若商品符合售后条件，可申请退款 refund。退款执行前必须由用户确认；"
            "高金额退款 high-value refund 需要人工客服审核。原路退款到账时间取决于支付渠道。",
        ),
        RetrievalDocument(
            "KB-SHIPPING-01",
            "物流与配送 Shipping tracking carrier status",
            "已发货订单可查询物流 tracking 状态和承运商信息。运输中的订单 in transit 不能直接"
            "发起已签收商品的退货流程；预计送达时间 delivery estimate 以物流更新为准。"
            " Shipping status includes carrier information and package tracking.",
        ),
        RetrievalDocument(
            "KB-RETURN-01",
            "退货政策 Return policy",
            "已签收订单可以申请退货 return。系统先创建待确认动作，用户确认后才提交退货申请。"
            "商品需满足退货条件，部分特殊品类可能不支持无理由退货。",
        ),
        RetrievalDocument(
            "KB-COUPON-01",
            "优惠券与促销 Coupon policy",
            "优惠券 coupon 能否使用取决于有效期、适用商品范围和订单门槛。促销码 promo code"
            "不能绕过营销规则，通常不可与明确标注互斥的活动叠加。",
        ),
        RetrievalDocument(
            "KB-ADDRESS-01",
            "收货地址修改 Shipping address changes",
            "订单未进入仓库锁定或发货阶段时，可以申请修改收货地址 shipping address。"
            "已发货订单通常不能直接改址，需要联系人工客服确认承运商能力。",
        ),
        RetrievalDocument(
            "KB-INVOICE-01",
            "发票与账单 Invoice and billing",
            "已支付订单可以按平台规则申请发票 invoice。账单 billing 信息应与订单和支付记录一致；"
            "发票抬头、税号等字段提交后如需修改，可能需要重新开具。",
        ),
        RetrievalDocument(
            "KB-WARRANTY-01",
            "保修与质量问题 Warranty coverage",
            "商品 warranty 保修范围取决于品类和厂商条款。质量问题应保留订单、故障描述和必要凭证；"
            "超过普通退货期不代表一定失去保修资格。",
        ),
        RetrievalDocument(
            "KB-ACCOUNT-01",
            "账户与登录安全 Account security",
            "忘记密码 password 时应通过官方重置流程验证账户身份。客服不会索要完整密码、验证码"
            "或支付密钥。发现异常登录 suspicious login 时应立即修改密码并检查账户安全设置。",
        ),
        RetrievalDocument(
            "KB-SUBSCRIPTION-01",
            "订阅取消 Subscription cancellation and renewal",
            "SaaS subscription 订阅可在符合套餐规则时取消自动续费 cancel renewal。取消续费不会"
            "自动承诺退款；已经产生的账单是否可退仍按退款和合同规则处理。"
            " Cancel auto renewal does not guarantee a refund.",
        ),
        RetrievalDocument(
            "KB-PRIVACY-01",
            "隐私与数据请求 Privacy request",
            "用户可按隐私政策提交个人数据访问、更正或删除 data deletion 请求。涉及身份敏感操作时"
            "需要先完成身份验证；客服回复不得暴露其他客户数据。",
        ),
    ]


class KnowledgeService:
    """Grounded knowledge service backed by hybrid retrieval and answerability gating."""

    def __init__(
        self,
        model: OpenAICompatibleModel | None = None,
        *,
        retriever: HybridRetriever | None = None,
        documents: list[RetrievalDocument] | None = None,
        min_evidence_score: float = 0.16,
    ) -> None:
        self.model = model
        self.documents = documents or default_knowledge_documents()
        if retriever is None:
            dense = InMemoryDenseRetriever(
                self.documents,
                DeterministicHashEmbedding(),
            )
            retriever = HybridRetriever(
                self.documents,
                dense_retriever=dense,
                sparse_retriever=BM25Retriever(self.documents),
            )
        self.retriever = retriever
        self.min_evidence_score = min_evidence_score

    def search(self, query: str, limit: int = 3) -> list[KnowledgeCitation]:
        hits = self.retriever.search(query, limit=max(limit, 1), prefetch=max(10, limit * 3))
        if not hits or hits[0].evidence_score < self.min_evidence_score:
            return []

        accepted = [
            hit
            for hit in hits
            if hit.evidence_score >= self.min_evidence_score
            and hit.evidence_score >= hits[0].evidence_score * 0.55
        ][:limit]
        return [
            KnowledgeCitation(
                document_id=hit.document.document_id,
                title=hit.document.title,
                snippet=hit.document.text,
                score=round(hit.evidence_score, 4),
            )
            for hit in accepted
        ]

    def answer(self, query: str, citations: list[KnowledgeCitation]) -> str:
        if not citations:
            return "当前知识库没有足够证据回答这个问题，建议转人工客服处理。"
        if self.model is None:
            top = citations[0]
            return f"[{top.document_id}] {top.snippet}"

        evidence = "\n".join(
            f"[{item.document_id}] {item.title}: {item.snippet}" for item in citations
        )
        system = (
            "You are a customer-support answer composer. Answer only from the supplied evidence. "
            "Do not invent policies, order state, refunds, or actions. "
            "If evidence is insufficient, say that human support is required. "
            "Every factual policy claim must retain a supplied source id such as [KB-...]."
        )
        user = f"Question:\n{query}\n\nEvidence:\n{evidence}"
        try:
            return self.model.chat_text(system=system, user=user)
        except ModelGatewayError:
            top = citations[0]
            return f"[{top.document_id}] {top.snippet}"

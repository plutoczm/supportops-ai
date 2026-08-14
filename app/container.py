from __future__ import annotations

from dataclasses import dataclass

from app.config import Settings
from app.guardrails import InputGuardrails
from app.knowledge import KnowledgeService
from app.model_gateway import OpenAICompatibleModel
from app.orchestrator import SupportOrchestrator
from app.policy import ActionPolicy
from app.router import IntentRouter
from app.store import SupportStore
from app.tools import SupportTools


@dataclass(slots=True)
class ServiceContainer:
    settings: Settings
    store: SupportStore
    tools: SupportTools
    knowledge: KnowledgeService
    orchestrator: SupportOrchestrator


def build_container(settings: Settings | None = None) -> ServiceContainer:
    settings = settings or Settings.from_env()
    store = SupportStore(settings.database_url)
    store.create_schema()
    store.seed_demo_data()

    model = None
    if settings.llm_enabled:
        model = OpenAICompatibleModel(
            base_url=settings.llm_base_url or "",
            model=settings.llm_model or "",
            api_key=settings.llm_api_key,
        )

    guardrails = InputGuardrails()
    router = IntentRouter(model=model)
    knowledge = KnowledgeService(model=model)
    policy = ActionPolicy(settings.refund_human_review_threshold)
    tools = SupportTools(store)
    orchestrator = SupportOrchestrator(
        store=store,
        guardrails=guardrails,
        router=router,
        knowledge=knowledge,
        policy=policy,
        tools=tools,
    )
    return ServiceContainer(
        settings=settings,
        store=store,
        tools=tools,
        knowledge=knowledge,
        orchestrator=orchestrator,
    )

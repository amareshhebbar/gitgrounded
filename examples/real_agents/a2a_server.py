import os
import sys

import support
import uvicorn
from a2a.helpers import new_text_message
from a2a.server.agent_execution import AgentExecutor
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill
from starlette.applications import Starlette


class SupportExecutor(AgentExecutor):
    async def execute(self, context, event_queue) -> None:
        text = context.get_user_input()
        topic = support.topic_of(text)
        reply = support.answer_from(support.lookup_policy(topic) if topic else None)
        await event_queue.enqueue_event(new_text_message(reply, context_id=context.context_id))

    async def cancel(self, context, event_queue) -> None:
        raise RuntimeError("cancel not supported")


def build_app(url: str, v03_compat: bool = True) -> Starlette:
    card = AgentCard(
        name="support-agent",
        description="Answers refund and shipping questions from policy",
        version="1.0.0",
        supported_interfaces=[AgentInterface(url=url, protocol_binding="JSONRPC", protocol_version="1.0")],
        capabilities=AgentCapabilities(streaming=False),
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        skills=[AgentSkill(id="support", name="support", description="refunds and shipping", tags=["support"])],
    )
    handler = DefaultRequestHandler(agent_executor=SupportExecutor(), task_store=InMemoryTaskStore(), agent_card=card)
    routes = create_agent_card_routes(card) + create_jsonrpc_routes(handler, "/", enable_v0_3_compat=v03_compat)
    return Starlette(routes=routes)


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.environ.get("PORT", "9999"))
    uvicorn.run(build_app(f"http://127.0.0.1:{port}/"), host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()

from typing import Any

import support
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool
from langgraph.graph import START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition


@tool
def lookup_policy(topic: str) -> str:
    """Return the support policy text for a topic: refund or shipping."""
    return support.lookup_policy(topic)


class ScriptedChatModel(BaseChatModel):
    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "ScriptedChatModel":
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        last = messages[-1]
        if isinstance(last, ToolMessage):
            msg = AIMessage(content=support.answer_from(str(last.content)))
        else:
            human = next(m for m in reversed(messages) if isinstance(m, HumanMessage))
            topic = support.topic_of(str(human.content))
            if topic:
                msg = AIMessage(
                    content="", tool_calls=[{"name": "lookup_policy", "args": {"topic": topic}, "id": "call_1"}]
                )
            else:
                msg = AIMessage(content=support.answer_from(None))
        msg.usage_metadata = {"input_tokens": 20, "output_tokens": 8, "total_tokens": 28}
        return ChatResult(generations=[ChatGeneration(message=msg)])


def chat_model():
    name = support.real_model()
    if name:
        from langchain.chat_models import init_chat_model

        return init_chat_model(name)
    return ScriptedChatModel()


def build_graph():
    model = chat_model().bind_tools([lookup_policy])

    def agent(state: MessagesState):
        return {"messages": [model.invoke([("system", support.SYSTEM_PROMPT), *state["messages"]])]}

    g = StateGraph(MessagesState)
    g.add_node("agent", agent)
    g.add_node("tools", ToolNode([lookup_policy]))
    g.add_edge(START, "agent")
    g.add_conditional_edges("agent", tools_condition)
    g.add_edge("tools", "agent")
    return g.compile()

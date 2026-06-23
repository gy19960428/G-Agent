from __future__ import annotations

from g_agent_ng.llm.base import LLMClient
from g_agent_ng.llm.models import ModelMessage, ModelRequest, ToolSpec
from g_agent_ng.runtime.context import RunContext
from g_agent_ng.runtime.models import RuntimeEvent, TurnRequest, TurnResult
from g_agent_ng.tools.registry import ToolRegistry


class RuntimeEngine:
    def __init__(self, model: LLMClient, tools: ToolRegistry | None = None) -> None:
        self._model = model
        self._tools = tools or ToolRegistry()

    async def run_turn(self, request: TurnRequest, context: RunContext | None = None) -> TurnResult:
        ctx = context or RunContext()
        events: list[RuntimeEvent] = [RuntimeEvent("turn_started", {"session_id": request.session_id})]
        output: list[str] = []

        try:
            model_request = ModelRequest(
                messages=(ModelMessage(role="user", content=request.user_text),),
                tools=tuple(ToolSpec(t.name, t.description, t.input_schema) for t in self._tools.list()),
            )
            async for model_event in self._model.stream(model_request, ctx):
                ctx.cancellation.raise_if_cancelled()
                if model_event.type == "text":
                    output.append(model_event.text)
                    events.append(RuntimeEvent("model_delta", {"text": model_event.text}))
                elif model_event.type == "tool_call" and model_event.tool_call is not None:
                    call = model_event.tool_call
                    events.append(RuntimeEvent("tool_requested", {"name": call.name, "call_id": call.call_id}))
                    tool = self._tools.get(call.name)
                    events.append(RuntimeEvent("tool_started", {"name": call.name, "call_id": call.call_id}))
                    result = await tool.run(call.arguments, ctx)
                    events.append(
                        RuntimeEvent(
                            "tool_finished",
                            {
                                "name": call.name,
                                "call_id": call.call_id,
                                "ok": result.ok,
                                "content": result.content,
                                "error": result.error,
                            },
                        )
                    )
                elif model_event.type == "error":
                    raise RuntimeError(model_event.text or "model provider error")
            final_text = "".join(output)
            events.append(RuntimeEvent("turn_finished", {"text": final_text}))
            return TurnResult(request.session_id, final_text, tuple(events))
        except Exception as exc:
            events.append(RuntimeEvent("turn_failed", {"error": str(exc)}))
            return TurnResult(request.session_id, "", tuple(events), ok=False, error=str(exc))

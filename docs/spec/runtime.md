# Runtime Specification

The runtime processes one user turn at a time. A turn is represented by `TurnRequest` and produces a `TurnResult` plus an ordered event stream.

## Turn lifecycle

1. Accept user input and current session context.
2. Build a provider-neutral model request.
3. Stream model events.
4. When the model requests tools, validate and execute them through the tool executor.
5. Feed tool results back to the model if continuation is required.
6. Finish with a final assistant message or a structured failure.

## Events

Required event categories:

- `turn_started`
- `model_delta`
- `tool_requested`
- `tool_started`
- `tool_finished`
- `turn_finished`
- `turn_failed`

Events must be serializable and frontend-neutral.

## Cancellation and budget

The engine receives a runtime budget with max model rounds, max tool calls, and wall-clock timeout. Cancellation is cooperative: each provider and tool receives a context object.

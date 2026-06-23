# G-Agent Next Product Specification

G-Agent Next is an automation agent runtime with a command-line interface, a typed tool protocol, optional UI adapters, and pluggable model providers.

The project is defined by behavior rather than by any previous implementation. Runtime modules communicate through typed requests, events, and results. UI layers render events and submit user actions; they do not own agent state.

## Goals

- Run a user turn from input to final answer.
- Stream model output as events.
- Execute declared tools with validation, timeout, and structured results.
- Persist sessions in a replaceable storage layer.
- Support browser automation through a small controller interface.
- Keep frontends replaceable: terminal, bot, desktop, or web adapters consume the same event stream.

## Non-goals for the initial rewrite

- Preserve legacy module names or internal APIs.
- Copy legacy tests, documentation, assets, prompts, or memory files.
- Provide every historical frontend before the runtime is stable.

## Compatibility policy

The legacy runtime may coexist during migration. New code lives under `g_agent_ng` until it passes the acceptance checks, then entry points can be moved deliberately.

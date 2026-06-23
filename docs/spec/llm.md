# LLM Provider Specification

The model layer exposes provider-neutral clients. Providers translate internal messages and tool descriptors into vendor-specific requests.

## Interfaces

- `LLMClient.stream(request, context)` returns asynchronous `ModelEvent` objects.
- `ModelRequest` contains messages, tools, provider options, and metadata.
- `ModelEvent` may be text, tool call, usage, finish, or error.

## Provider rules

- Provider adapters should be small and isolated.
- Streaming parsers must not mutate session state directly.
- Tool-call assembly is provider-specific but normalized before reaching runtime.

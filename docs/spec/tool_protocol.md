# Tool Protocol Specification

Tools are registered as independent descriptors. The runtime never dispatches by a monolithic name switch.

## Tool descriptor

Each tool declares:

- `name`: stable machine-readable identifier.
- `description`: short human-readable purpose.
- `input_schema`: JSON-schema-like object for validation.
- `run(args, context)`: execution function returning `ToolResult`.

## Tool result

Results contain:

- `ok`: boolean success flag.
- `content`: concise model-facing text.
- `metadata`: optional structured data.
- `error`: optional error code and message.

## Safety and execution

The executor owns cwd, timeout, environment policy, stdout/stderr limits, and concurrency. Tool implementations should not mutate global runtime state directly.

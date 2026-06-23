# UI Adapter Specification

UI adapters are consumers and producers of runtime events.

## Responsibilities

- Convert user messages into `TurnRequest`.
- Render runtime events.
- Send explicit user actions such as cancel, approve, or answer prompt.

## Non-responsibilities

- Building prompts.
- Executing tools.
- Owning model sessions.

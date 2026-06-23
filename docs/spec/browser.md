# Browser Control Specification

Browser automation is exposed as a controller interface. The runtime does not depend on a specific browser library.

## Controller capabilities

- List tabs.
- Capture a structured page snapshot.
- Click by target reference.
- Type text by target reference.
- Evaluate a limited script when explicitly requested by a tool.

## Snapshot model

Snapshots prefer structured elements over raw HTML. Each element includes role, accessible name, visibility, bounds when available, and a stable reference id.

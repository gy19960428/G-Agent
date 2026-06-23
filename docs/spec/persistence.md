# Persistence Specification

Persistence stores sessions, turn events, and configuration references. It does not store secrets directly.

## Stores

- Session store: metadata and message history.
- Event store: append-only turn events for replay.
- Config store: paths and non-secret preferences.

Secrets are referenced by name and resolved by external configuration.

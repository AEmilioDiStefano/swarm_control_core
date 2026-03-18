# ADR-0003: Benign aioice STUN Retry Race Handling

- Status: Accepted
- Date: 2026-03-13
- Scope: `swarm_control_core` only

## Context

During switch/teardown timing windows, asyncio loop logs could include benign aioice callback noise:

- `Transaction.__retry`
- `InvalidStateError: invalid state`

This noise can obscure actionable failures and slow debugging.

## Decision

- Extend the UI loop exception filter to suppress known benign aioice STUN retry race events.
- Keep all non-matching exceptions on the normal error path.

## Why This Works

- Removes expected race noise while preserving visibility into real failures.
- Improves signal-to-noise in runtime logs and operator debugging sessions.

## Tradeoffs

- Any suppression must stay narrowly scoped to known benign signatures.
- Over-broad filtering could hide real defects.

## Guardrails

- Filter only known callback/message patterns tied to this specific benign race.
- Keep all other exceptions visible via default exception handlers.

## Related

- [ADR-0002: Low-Latency Robot-Switch Hardening](./ADR-0002-low-latency-switch-hardening.md)

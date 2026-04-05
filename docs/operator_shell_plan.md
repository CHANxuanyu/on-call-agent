# Operator Shell Plan

## Scope

Add one interactive operator shell on top of the existing deployment-regression runtime without
replacing the current direct CLI commands or changing the verifier-driven control plane.

## Implementation Steps

1. Extend durable session state with a narrow operator shell mode record and safe defaults so
   existing checkpoints, replay flows, and direct CLI commands continue to load unchanged.
2. Add a small runtime shell surface that wraps the current live/inspect/export commands, exposes
   compact session status, and records shell mode changes durably through the checkpoint seam.
3. Introduce a narrow `auto-safe` gate only for the existing deployment-regression rollback path:
   auto-execute only when the verified rollback candidate, target allowlist, expected versions,
   approval policy, and resolved-gap checks all pass; otherwise degrade to `semi-auto` and persist
   the downgrade reason.
4. Add an interactive line-oriented `shell` CLI entrypoint with slash commands for help, mode,
   new/resume, status, inspect, audit, approve, deny, verify, handoff, and exit.
5. Update usage/demo documentation and add focused tests for shell command behavior, durable mode
   state, auto-safe degradation, and existing direct CLI command compatibility.

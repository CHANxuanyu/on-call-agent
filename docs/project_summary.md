# Project Summary

## Positioning

This repository is a verifier-driven, durable, approval-gated incident-response runtime. It is
designed to show runtime engineering quality rather than product breadth: typed contracts, durable
artifacts, checkpoint-driven resumability, replayable failure handling, explicit approval
boundaries, and one honest operator-facing product slice over that runtime.

## Runtime Milestones Completed

- narrow incident workflow chain from triage through approval-gated action stub
- single-scenario live deployment-regression path with approval-gated bounded rollback and
  external outcome verification
- append-only structured transcripts and resumable checkpoints
- `SessionArtifactContext` for shared artifact reconstruction
- synthetic failure invariants for malformed, missing, or partial runtime paths
- shared resumable-slice harness for repeated execution wiring
- permission provenance and approval-aware state persistence
- first incident-working-memory slice
- operator shell with `manual`, `semi-auto`, and fail-closed `auto-safe`
- operator-facing handoff context assembly
- stable handoff artifact writing and deterministic regeneration

## Why It Matters

A lot of agent projects show capability but not runtime discipline. This project focuses on the
engineering layer that makes stateful agent behavior credible: verifiers decide completion,
artifacts remain inspectable, failures stay replayable, risky next steps stay explicitly gated,
and the current live demo path stays narrow enough to be honest.

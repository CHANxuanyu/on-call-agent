# Positioning

## Core Positioning

On-Call Copilot is an incident decision and verification product built on a verifier-driven,
durable, approval-gated runtime.

It is not a coding copilot.

## Crisp Comparison Against Claude Code

Claude Code is a coding copilot.  
On-Call Copilot is an incident decision and verification product.  
Claude Code helps engineers change systems.  
On-Call Copilot helps operators decide whether to act now, which bounded action is safe, and how
recovery is verified.

The two products can share harness ideas, but they solve different operator problems.

## Reusable Short Version

On-Call Copilot is a narrow operator product for incident decision, approval, and verification.
Claude Code helps engineers write and change code. This repository focuses on safe incident loops,
not coding workflows.

## Reusable Longer Version

This repository is not trying to clone Claude Code. It applies some durable agent-harness ideas to
a different product: an on-call copilot that helps an operator inspect incident state, review a
bounded mitigation candidate, preserve approval boundaries, and verify recovery from external
runtime evidence.

## What To Say

- verifier-driven incident-response runtime
- demo-grade ops agent for one incident family
- operator-facing shell and future console direction
- approval-gated rollback with external outcome verification

## What Not To Say

- Claude Code for ops
- autonomous SRE platform
- mature production incident management product
- broad self-healing infrastructure agent

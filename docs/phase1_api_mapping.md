# Phase 1 API Mapping

This document explains how the Phase 1 Operator Console backend contract maps to existing runtime
truth. The contract is implemented in [console_api.py](/home/chan/projects/on-call-agent/src/runtime/console_api.py).

There is no second control model. Every field comes from an existing durable runtime seam.

## Suggested Surface Map

| Console surface | Adapter method | Suggested route | Runtime truth used |
| --- | --- | --- | --- |
| Sessions list | `OperatorConsoleAPI.list_sessions()` | `GET /phase1/sessions` | checkpoint files plus transcript events |
| Session detail | `OperatorConsoleAPI.get_session_detail()` | `GET /phase1/sessions/{session_id}` | `SessionArtifactContext`, checkpoint, transcripts, existing handoff artifact |
| Timeline | `OperatorConsoleAPI.get_session_timeline()` | `GET /phase1/sessions/{session_id}/timeline` | transcript events only |
| Approval / deny | `OperatorConsoleAPI.resolve_approval()` | `POST /phase1/sessions/{session_id}/approval` | existing live approval-resolution surface |
| Verification view | `OperatorConsoleAPI.get_verification_result()` | `GET /phase1/sessions/{session_id}/verification` | latest outcome-verification artifact resolution |
| Verification rerun | `OperatorConsoleAPI.rerun_verification()` | `POST /phase1/sessions/{session_id}/verification` | existing live verification surface |
| Handoff access | `OperatorConsoleAPI.get_handoff_artifact()` | `GET /phase1/sessions/{session_id}/handoff` | existing handoff artifact store |
| Handoff export | `OperatorConsoleAPI.export_handoff_artifact()` | `POST /phase1/sessions/{session_id}/handoff/export` | existing handoff regeneration seam |

## Field Grounding

### Sessions list

- `session_id`, `incident_id`, `current_phase`, `requested_mode`, `effective_mode`,
  `approval_status`, `last_updated`
  Source: session checkpoint JSON
- `family`
  Source: structured triage input reconstructed from transcript `tool_request` events
- `latest_verifier_summary`
  Source: latest `verifier_result` transcript event

### Session detail

- `checkpoint_id`, `current_step`, `summary_of_progress`, `approval`, `pending_verifier`
  Source: current checkpoint
- `family`, `next_recommended_action`, `current_evidence_summary`, `latest_verifier_summary`
  Source: `SessionArtifactContext` and the same shell status helpers already used by the operator shell
- `handoff.available`, `handoff.handoff_path`, `handoff.artifact`
  Source: existing handoff artifact file, if present

### Timeline

- every entry is built from transcript events already recorded by the runtime
- `checkpoint` entries come from `checkpoint_written`
- `verifier` entries come from `verifier_result`
- `approval` entries come from `approval_resolved`
- `permission` entries come from `permission_decision`
- `resume` entries come from `resume_started`
- `execution` / `verification` entries come from rollback or outcome-probe tool request/result events

### Approval and verification actions

- approval and deny actions delegate to `run_resolve_deployment_regression_approval()`
- verification reruns delegate to `run_verify_deployment_regression_outcome()`
- these adapters do not change action semantics; they only return updated session detail and
  verification state after the existing runtime call completes

### Handoff access

- read access uses the current on-disk handoff artifact if one exists
- export access delegates to `IncidentHandoffArtifactRegenerator`
- no handoff content is synthesized outside the current regeneration seam

## Invariants

- no second state store
- no hidden control state
- no approval bypass
- no verifier bypass
- no new incident-family semantics
- shell and CLI remain separate operator surfaces over the same runtime truth

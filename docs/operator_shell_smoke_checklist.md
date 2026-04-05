# Operator Shell Smoke Checklist

This is a human-guided local smoke pass for the current deployment-regression shell. It does not
replace the existing automated tests.

Use it alongside the [Usage Guide](usage.md) and [Demo Guide](demo.md) when you want a repeatable
local operator-shell check without guessing the current command flow.

## 1. Setup

Command

```bash
scripts/test_operator_shell_smoke.sh
```

Success looks like

- It prints isolated smoke roots under `/tmp`
- It prints separate commands for the demo-target terminal and shell terminal
- It prints an `AUTO_SAFE_SETTINGS` path for the bounded auto-safe success check

Failure or red flags

- `.venv` is missing
- `docs/examples/deployment_regression_payload.json` is missing
- The script output does not match the current `python -m runtime.cli shell` surface

## 2. Demo Target

Command

```bash
cd /home/chan/projects/on-call-agent
source .venv/bin/activate
python -m runtime.cli run-demo-target --port 8001
```

Success looks like

- The demo target starts on `http://127.0.0.1:8001`
- Leave it running while exercising the shell

Failure or red flags

- Port `8001` is unavailable
- The demo target exits immediately

Reset note

- Stop with `Ctrl-C`
- Restart the same command to reset the runtime state to bad version `2.1.0`

## 3. Semi-Auto Path

Command

```bash
cd /home/chan/projects/on-call-agent
source .venv/bin/activate
python -m runtime.cli shell \
  --checkpoint-root <CHECKPOINT_ROOT> \
  --transcript-root <TRANSCRIPT_ROOT> \
  --handoff-root <HANDOFF_ROOT>
```

Inside the shell

```text
/mode semi-auto
/new docs/examples/deployment_regression_payload.json
/status
/inspect session
```

Success looks like

- The shell prints `created new session: <generated session id>`
- `/status` shows `requested=semi-auto effective=semi-auto`
- The session stops at `action_stub_pending_approval`
- Approval is `pending` for `rollback_recent_deployment_candidate`

Failure or red flags

- The shell silently reuses a previous completed session
- The runtime skips straight to execution in `semi-auto`
- The runtime proposes no rollback candidate while the demo target is still on the bad release

Optional deny check

```text
/deny Smoke-test denial path.
```

Success looks like

- The phase becomes `action_stub_denied`
- No rollback executes

Failure or red flags

- Deny still mutates the target service
- Approval remains `pending` without explanation

## 4. Approve Path

Command

```text
/approve Smoke-test approval for bounded rollback.
/verify
/handoff
/status
```

Success looks like

- The phase becomes `outcome_verification_succeeded`
- Approval is `approved`
- Verifier/evidence summary mentions recovery on version `2.0.9`
- Handoff export is written

Failure or red flags

- Approval is recorded but rollback does not happen
- Outcome verification does not see healthy recovery
- Handoff export is missing after a successful outcome verification

## 5. Fresh-Session Check

Command

```text
/new docs/examples/deployment_regression_payload.json
```

Success looks like

- A new `created new session: ...` line appears
- The new session id is different from the prior session id
- Prior session artifacts remain inspectable and are not silently overwritten

Failure or red flags

- The shell silently drops you back into the previous session
- The session id is unchanged without explicit reuse

## 6. Healthy / No-Action Path

Command

```text
/new docs/examples/deployment_regression_payload.json
/status
/inspect session
```

Run this after the demo target has already recovered to `2.0.9`.

Success looks like

- The new session gets a fresh session id
- The phase is `action_stub_not_actionable`
- Approval status is `none`
- The reason says the service is already healthy or already on the known-good version
- No rollback candidate is produced

Failure or red flags

- The runtime still reaches `action_stub_pending_approval`
- A rollback candidate is proposed while the service is already healthy on `2.0.9`

## 7. Auto-Safe Degrade Path

Command

```bash
cd /home/chan/projects/on-call-agent
source .venv/bin/activate
python -m runtime.cli shell \
  --checkpoint-root <CHECKPOINT_ROOT> \
  --transcript-root <TRANSCRIPT_ROOT> \
  --handoff-root <HANDOFF_ROOT>
```

Inside the shell

```text
/mode auto-safe
/new docs/examples/deployment_regression_payload.json
/status
```

Success looks like

- With default settings, auto-safe fails closed when the policy is disabled
- The shell degrades to `semi-auto` with a clear printed reason
- `/status` or `/inspect session` shows `requested=auto-safe effective=semi-auto`

Failure or red flags

- Auto-safe executes without policy enablement
- The shell degrades without a durable reason

## 8. Auto-Safe Success Path

First reset the demo target so the bad release is active again.

Command

```bash
cd /home/chan/projects/on-call-agent
source .venv/bin/activate
python -m runtime.cli shell \
  --checkpoint-root <CHECKPOINT_ROOT> \
  --transcript-root <TRANSCRIPT_ROOT> \
  --handoff-root <HANDOFF_ROOT> \
  --settings-path <AUTO_SAFE_SETTINGS>
```

Inside the shell

```text
/mode auto-safe
/new docs/examples/deployment_regression_payload.json
/status
```

Success looks like

- Either the bounded rollback auto-executes and reaches `outcome_verification_succeeded`
- Or the shell degrades to `semi-auto` with a clear reason
- If it succeeds, the verifier summary shows healthy recovery on `2.0.9`

Failure or red flags

- Auto-safe executes outside the bounded rollback path
- Auto-safe succeeds without the allowlisted target or without clear recovery evidence
- The shell degrades but does not record why

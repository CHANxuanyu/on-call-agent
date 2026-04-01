+++
name = "incident-triage"
purpose = "Establish a safe first-pass incident picture before deeper execution."
when_to_use = "Use when a new alert or incident page arrives and the harness needs a structured triage pass."
required_inputs = ["alert payload or incident summary"]
optional_inputs = ["recent deployment context", "runbook link", "service ownership metadata"]
expected_outputs = ["initial incident summary", "suspected blast radius", "recommended next read-only checks"]
verifier_expectations = ["follow-up investigation should confirm or reject the initial triage hypothesis"]
permission_notes = ["prefer read-only tools during triage", "defer write actions until a human-approved plan exists"]
examples = ["Triage sustained 5xx alerts before selecting deeper diagnostic tools."]
+++

# Incident Triage

## Goal

Create a compact first-pass view of the incident before the harness commits to deeper execution.

## Operating Guidance

- Restate the trigger in concrete operational terms.
- Identify the likely impacted service, users, and time window.
- Prefer read-only evidence collection first.
- Surface missing context that blocks confident action.

## Expected Output Shape

- incident summary
- likely scope or blast radius
- immediate read-only next checks
- explicit unknowns

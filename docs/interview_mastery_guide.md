# Interview Mastery Guide

This guide is for technical interviews where the goal is to explain the repository clearly,
defensibly, and without overselling it.

The right framing is:

- this is a completed runtime milestone
- it is a narrow incident-response harness, not a finished product
- its value is in runtime discipline: verification, durability, resumability, replay, safety, and
  handoff quality

## 1. Project Positioning

### What This Project Is

This repository is a verifier-driven incident-response runtime prototype written in Python. It
implements a narrow, deterministic incident step chain with typed tools, typed verifiers,
append-only transcripts, resumable checkpoints, explicit permission boundaries, and operator-facing
handoff artifacts.

The implemented chain is:

`triage -> follow-up -> evidence -> hypothesis -> recommendation -> approval-gated action stub`

### What This Project Is Not

It is not:

- a generic coding agent
- a broad autonomous operations platform
- a multi-agent workflow engine
- a remediation system that writes to real external systems
- a productized UI or approval workflow

### Why It Exists

Many agent demos show that a model can call tools. Far fewer show durable runtime guarantees:

- what state is authoritative
- how the system resumes after interruption
- how failures stay visible and replayable
- how risky actions remain explicitly gated
- how operator handoff is reconstructed from real runtime state

This project exists to make those guarantees concrete for incident-response workflows.

### What Problem It Solves

It solves a runtime design problem, not a broad product problem:

- how to move an incident through a narrow investigation chain without treating model output as
  truth
- how to keep execution history inspectable
- how to separate control state, execution truth, semantic memory, and derived handoff output
- how to stop safely at the point where approval becomes the real next problem

### How It Differs From A Coding Agent Like Claude Code

Claude Code is a much broader coding/product agent. This repository borrows only some harness
ideas:

- durable artifacts
- resumability
- structured failure handling
- explicit permission reasoning

It applies those ideas to incident-response state instead of coding workflows. The result is much
narrower and much more domain-specific.

### Why An Incident-Response Runtime Needs Different Guarantees

Incident response is not just "tool use with a different prompt." It needs stronger guarantees
because:

- the system must show what evidence justified the next step
- control state cannot be hidden in chat history
- operators need reliable handoff artifacts
- unsafe autonomy is a real bug, not just a UX issue
- conservative behavior is sometimes the correct behavior

In other words, the runtime has to be auditable and resumable before it has to be broad.

## 2. One-Minute, Three-Minute, And Deep-Dive Explanations

### 60-90 Second Spoken Intro

I built a verifier-driven incident-response runtime in Python. The important part is not that a
model can call a tool. The important part is the harness around that behavior: append-only
structured transcripts, checkpoint-driven resumability, verifier-gated state transitions, explicit
permission provenance, synthetic failure handling, and deterministic handoff regeneration. The
implemented runtime is deliberately narrow: it moves an incident from triage through follow-up,
evidence, hypothesis, recommendation, and an approval-gated action stub. It stops before real
execution on purpose. That makes it a strong runtime-engineering project because it proves
replayability, auditability, and safety boundaries without pretending to solve broader automation
or productization.

### 2-3 Minute Version

The project started from a runtime question rather than a product question. A lot of agent systems
can produce tool calls, but they often leave state, failure handling, and resumability implicit. I
wanted to build something narrower and more defensible for incident-response workflows.

So I made the state model explicit. Checkpoints store control-plane state like the current phase,
current step, pending verifier, approval state, and progress summary. Transcripts are append-only
JSONL and record what actually happened: model-step notes, permission decisions, tool requests,
tool results, verifier results, and checkpoint writes. The system only advances after verifiers
pass. "The tool returned something" is not treated as completion.

On top of that, I added `SessionArtifactContext`, which reconstructs the latest usable verified
artifacts from checkpoints and transcripts. That removes repeated step-local reconstruction logic
and gives the runtime a consistent way to distinguish verified success, insufficiency, and
structured synthetic failure. Synthetic failures matter because malformed outputs, missing verifier
results, and interrupted paths should stay replayable instead of collapsing into hidden exceptions
or `None`.

The implemented chain is triage, follow-up target selection, evidence reading, incident
hypothesis, recommendation, and an approval-gated action stub. The runtime does not execute
remediation. It stops when it can justify a candidate and make the approval boundary explicit. I
also added a first incident-working-memory slice plus handoff context assembly and stable handoff
artifact regeneration so operator-facing output can be rebuilt deterministically from durable
runtime state.

### 5-7 Minute Technical Walkthrough

Start with the problem definition. This repository is trying to answer: what would a reliable
incident-response runtime look like before real execution is allowed?

The first design choice is a narrow step chain instead of a generic loop. The runtime implements
six typed slices:

1. `IncidentTriageStep` takes the initial incident payload, runs a read-only triage tool, verifies
   the output, writes the first checkpoint, and starts the transcript.
2. `IncidentFollowUpStep` resumes from durable state and decides whether there is exactly one safe
   read-only follow-up target worth investigating.
3. `IncidentEvidenceStep` uses that target to read one deterministic evidence bundle from fixtures.
4. `IncidentHypothesisStep` turns one evidence bundle into one structured incident hypothesis.
5. `IncidentRecommendationStep` turns one verified hypothesis into one structured recommendation.
6. `IncidentActionStubStep` turns one verified recommendation into an approval-aware action stub or
   an explicit non-actionable result.

The important part is how those steps move forward. Each step emits transcript events, runs a
verifier, and then writes a checkpointed phase. The phase change is verifier-driven. If a verifier
does not pass, the checkpoint preserves that state instead of pretending progress happened.

The second design choice is to separate state layers. Checkpoints are the control plane. They say
where the runtime is and what it is waiting on. Transcripts are execution truth. They record what
actually happened in append-only form. `IncidentWorkingMemory` is a semantic supplement that stores
compact verified incident understanding like leading hypothesis, unresolved gaps, and compact
handoff note. Handoff artifacts are derived again from checkpoints, verified artifacts, and
working memory. They are not part of the control plane.

The third design choice is shared artifact reconstruction through `SessionArtifactContext`.
Instead of making each later step parse transcript history itself, the context layer loads the
checkpoint and transcript once and exposes typed accessors for triage, follow-up, evidence,
hypothesis, recommendation, and action-stub artifacts. It also exposes insufficiency versus
failure. That distinction is important. Insufficiency means the runtime is conservatively not ready
to proceed. Synthetic failure means the runtime expected a durable artifact chain and found
something malformed or missing.

The fourth design choice is failure normalization. In `src/runtime/execution.py`, tool and
verifier execution are normalized into stable `ToolResult` and `VerifierResult` objects. If a tool
throws, returns an invalid structure, or returns output that fails typed validation, the runtime
creates a structured synthetic failure instead of leaking an ad hoc exception into the rest of the
system. That keeps negative paths replayable and auditable.

The fifth design choice is safety. Permission policy is intentionally simple: read-only tools are
allowed by default, write-capable tools would require approval, and dangerous tools are denied.
The key point is that the permission layer produces structured provenance explaining why a decision
was made. The runtime does not silently cross the execution boundary. The final slice writes
approval-aware state into the checkpoint instead of executing remediation.

The sixth design choice is operator-facing output. The repo includes
`SessionArtifactContext -> IncidentHandoffContextAssembler -> IncidentHandoffArtifactWriter`, plus
`IncidentHandoffArtifactRegenerator`. That means the handoff artifact can be rebuilt from durable
state and will fail honestly if the required artifact chain is missing or inconsistent.

Finally, I would close by saying the project is intentionally a milestone, not a product. It proves
that incident-oriented agent behavior can be verifier-driven, resumable, auditable, replayable,
and handoff-friendly before broadening into execution, integrations, or product surfaces.

## 3. Full Architecture Walkthrough

### Full Step Chain

#### `IncidentTriageStep`

- Entry point for a new incident.
- Loads the `incident-triage` skill asset.
- Runs a read-only triage tool.
- Writes transcript events directly.
- Verifies the triage output.
- Writes the first checkpoint with phase `triage_completed` on success.

#### `IncidentFollowUpStep`

- First resumable continuation slice.
- Loads checkpoint plus transcript state.
- Reconstructs prior triage artifacts.
- Chooses whether to investigate exactly one target or no-op conservatively.
- Verifies the follow-up outcome.
- Writes the next checkpoint phase.

#### `IncidentEvidenceStep`

- Starts using the shared resumable-slice harness.
- Reads one deterministic evidence bundle from local fixtures.
- Verifies that the evidence read matches the expected branch and target.
- Normalizes tool/verifier failures through the shared runtime helpers.

#### `IncidentHypothesisStep`

- Consumes one verified evidence artifact.
- Produces one structured incident hypothesis.
- Verifies whether the hypothesis is supported or conservative.
- Writes the first `IncidentWorkingMemory` snapshot on verifier-passed output.

#### `IncidentRecommendationStep`

- Consumes one verified hypothesis artifact.
- Produces one structured recommendation.
- Verifies that recommendation shape and branch are valid.
- Updates `IncidentWorkingMemory` with recommendation-level understanding.

#### `IncidentActionStubStep`

- Consumes one verified recommendation artifact.
- Produces either an approval-aware action candidate stub or a conservative
  `no_actionable_stub_yet` result.
- Writes `approval_state` into the checkpoint.
- Stops before execution.

### Verifier-Driven State Transitions

The runtime does not treat tool output as completion. The sequence is:

1. a tool returns structured output
2. a verifier evaluates that output and the branch context
3. only then does the step write the next checkpoint phase

This is the core design idea. The harness is "done" only when the verifier says the next state is
justified.

### Transcripts

Transcripts are append-only JSONL event streams under `sessions/transcripts/<session_id>.jsonl`.

Current event types:

- `resume_started`
- `model_step`
- `permission_decision`
- `tool_request`
- `tool_result`
- `verifier_result`
- `checkpoint_written`

Why they matter:

- they preserve execution truth in order
- they support replay and postmortem inspection
- they make hidden failure paths visible
- they allow artifact reconstruction without trusting in-memory state

### Checkpoints

Checkpoints live under `sessions/checkpoints/<session_id>.json` and hold control-plane state:

- `current_phase`
- `current_step`
- `pending_verifier`
- `approval_state`
- `summary_of_progress`

Why they matter:

- they make resumability explicit
- they answer "where is the runtime now?"
- they keep operator control state small and durable

What they do not do:

- store full execution history
- replace verifier-backed artifacts
- act as semantic incident memory

### `SessionArtifactContext`

`SessionArtifactContext` is the shared reconstruction seam for later slices.

It:

- loads the checkpoint and transcript once
- reconstructs the latest typed artifact per slice
- exposes verified and latest forms of artifacts
- exposes insufficiency vs synthetic failure
- exposes incident working memory read-only

This is one of the most important design pieces to explain well in interviews. It is what keeps
resume logic from being repeated across every step.

### Synthetic Failure Invariants

The runtime intentionally distinguishes two things:

#### Insufficiency

The system is conservatively not ready.

Examples:

- a required prior verifier has not passed
- a later slice is being asked to run from an incompatible phase

#### Synthetic Failure

The system expected a durable path and found a malformed or missing artifact.

Examples:

- tool execution exception
- invalid `ToolResult`
- output failing typed validation
- invalid `VerifierResult`
- missing verifier result where the checkpoint implies one should exist
- interrupted path with a request but no result

The important interview point is that failure is normalized into typed artifacts rather than
hidden in exceptions or implicit null handling.

### Shared Resumable-Slice Harness

`ResumableSliceHarness` centralizes common downstream-slice mechanics:

- load artifact context
- emit `resume_started`
- emit `model_step`
- run permission-checked read-only tool execution
- normalize synthetic failures
- run verifier execution
- write checkpoint plus transcript marker

Important nuance:

- `IncidentTriageStep` is still a direct first vertical slice
- `IncidentFollowUpStep` is resumable but still hand-wired
- `IncidentEvidenceStep`, `IncidentHypothesisStep`, `IncidentRecommendationStep`, and
  `IncidentActionStubStep` use the shared harness

That nuance is worth mentioning because it shows the codebase evolved incrementally instead of
through a giant rewrite.

### Permission Provenance

Permission policy is simple on purpose, but it is structured.

Current model:

- read-only tools -> `allow`
- write-capable tools -> `ask`
- dangerous tools -> `deny`

Current provenance includes:

- policy source
- action category
- evaluated action type
- whether approval is required
- rationale for conservative or denied decisions
- safety boundary
- future preconditions

That means the permission system is not only deciding; it is also producing audit artifacts.

### `IncidentWorkingMemory`

`IncidentWorkingMemory` is the first semantic-memory slice. It stores:

- leading hypothesis summary
- unresolved gaps
- important evidence references
- recommendation summary
- compact handoff note

It is:

- incident-scoped
- verifier-backed
- mutable latest snapshot
- supplementary to checkpoint and transcript truth

It is not:

- the source of truth for resume
- full transcript history
- a long-lived project-memory system

### Handoff Context, Artifact, And Regeneration

The handoff flow is layered:

`SessionArtifactContext -> IncidentHandoffContextAssembler -> IncidentHandoffArtifactWriter`

The assembler combines:

- checkpoint control state
- verified transcript-backed artifacts
- incident working memory when helpful

The writer persists one stable artifact:

- `sessions/handoffs/<incident_id>.json`

The regenerator can rebuild that artifact from a `session_id`. If the artifact chain is
insufficient or broken, it returns structured `written`, `insufficient`, or `failed` outcomes
instead of inventing a handoff.

## 4. Source-Of-Truth Model

### Control-Plane Truth

Control-plane truth is the checkpoint.

Interview-friendly explanation:

"The checkpoint tells me where the runtime is, what phase it is in, whether it is waiting on a
verifier, and whether approval is pending. It is the durable control state, not the full history."

### Execution Truth

Execution truth is the append-only transcript plus the verifier-backed artifacts reconstructed from
it.

Interview-friendly explanation:

"If I want to know what actually happened, I look at transcript events. That is the ordered record
of tool requests, tool results, verifier results, and checkpoint writes."

### Semantic Working Memory

Semantic working memory is `IncidentWorkingMemory`.

Interview-friendly explanation:

"This is the current verified understanding of the incident in compact form. It is useful for
handoff and context assembly, but it is not the thing I trust to reconstruct control flow."

### Operator-Facing Derived Artifact

The operator-facing derived artifact is the handoff context and stable handoff JSON.

Interview-friendly explanation:

"The handoff artifact is for operators. It is readable derived output. It is not used as resume
state, and it is not treated as execution truth."

### Why These Layers Are Separated

They are separated to avoid common agent-runtime mistakes:

- if checkpoints hold too much semantic state, they become brittle and hard to reason about
- if transcripts are treated like mutable summaries, auditability is lost
- if memory becomes hidden truth, replay and failure analysis get weaker
- if handoff artifacts become control state, derived output starts driving the runtime

The separation keeps each layer honest.

## 5. Design Tradeoffs

### Why The Project Stops At An Approval-Gated Action Stub

Because action candidacy and action execution are different safety problems.

This milestone proves:

- the runtime can justify a candidate
- approval state can be made explicit
- the system can stop conservatively at the right boundary

It deliberately does not claim:

- safe remediation semantics
- write execution policy
- rollback guarantees

### Why No Real Execution Or Remediation Was Added

Because real remediation would force a different class of guarantees:

- stronger approval mechanics
- integration-specific failure handling
- rollback and compensation logic
- real-world side effect verification

That would broaden scope faster than it would strengthen the current runtime story.

### Why No Generic Loop Was Introduced

The repo includes `AgentLoop` and `AgentRunner` as protocols, but not a broad execution loop.

That is intentional. The current milestone benefits more from explicit slice contracts than from an
abstract generic loop. A generic loop too early would make the runtime harder to explain and easier
to overclaim.

### Why No Multi-Agent System Was Added

Because multi-agent coordination would add:

- more concurrency
- more cross-agent state issues
- more approval and attribution complexity
- less clarity about which invariant belongs where

The repo is stronger as a single-runtime harness milestone than as an early multi-agent demo.

### Why Memory Was Split Conservatively

Only one semantic-memory slice was added because it already proves something important:

- semantic incident understanding can be separated from control state
- handoff context can be improved without making memory the source of truth

Project memory and broader promotion are intentionally deferred.

### Why Replay And Eval Matter

Replay matters because it turns architecture claims into testable behavior.

This repo includes narrow replay-style eval coverage to prove:

- supported branch behavior
- conservative branch behavior
- verifier pass rate across the chain
- stable handling of deterministic fixture-driven incidents

That is more useful for this milestone than a vague benchmark story.

## 6. Comparison With Claude Code

### What Ideas Were Borrowed

The project clearly borrows the following classes of ideas from mature agent harnesses:

- durable checkpoint and transcript separation
- resumability as a first-class runtime concern
- structured failure handling
- explicit permission reasoning
- file-based skill assets

### What Was Intentionally Not Copied

It intentionally does not copy:

- the broad coding-agent product surface
- generic conversation-first query orchestration
- multi-agent features
- hook-heavy lifecycle extension systems
- context compaction and transcript surgery
- broad execution capability

### Why This Project Keeps A Narrow Incident-Response Runtime Focus

Because the goal here is to show runtime engineering quality in a domain where:

- evidence quality matters
- state transitions should be verifier-backed
- approval boundaries matter
- operator handoff matters

That is a different optimization target than a coding assistant.

### Where Claude Code Is Stronger

Claude Code is stronger in areas that come with broader product scope:

- overall product breadth
- richer orchestration and context management
- broader coding workflow support
- more mature user-facing execution surface

That is not a weakness in this repo. It is a scope choice.

### Where This Project Is More Domain-Specific

This repo is more domain-specific in:

- explicit verifier-driven incident phase transitions
- checkpoint/transcript/working-memory/handoff separation
- incident-oriented action candidacy and approval-state persistence
- conservative branch handling when evidence is weak
- operator-facing handoff regeneration from durable state

### How To Answer "Why Not Just Use Claude Code?"

Strong answer:

"Claude Code is a stronger general coding agent, but this project is solving a different problem.
I wanted an incident-response runtime where state, verification, replay, approval boundaries, and
handoff artifacts are first-class runtime contracts. Borrowing broad product behavior would have
made the project less focused and harder to defend architecturally."

## 7. Module-By-Module Explanation

| Subsystem | Key Files | What It Does | Why It Exists | What Interviewers May Ask |
| --- | --- | --- | --- | --- |
| Step chain entry | `src/agent/incident_triage.py` | Creates the first durable triage slice from raw incident input | Establishes the first verified artifact and first checkpoint | Why is triage a direct vertical slice instead of using the shared harness? |
| First resumable continuation | `src/agent/incident_follow_up.py` | Resumes from durable state and selects one safe follow-up target | Shows checkpoint/transcript-based continuation before deeper evidence reading | Why can this step no-op? What makes that conservative rather than broken? |
| Shared downstream slices | `src/agent/incident_evidence.py`, `src/agent/incident_hypothesis.py`, `src/agent/incident_recommendation.py`, `src/agent/incident_action_stub.py` | Advance the durable incident artifact chain from evidence to action candidacy | Demonstrate reusable resumable-slice patterns without introducing a generic planner | Which parts are shared vs step-specific? |
| Future loop seams | `src/agent/loop.py`, `src/agent/runner.py`, `src/agent/state.py` | Define minimal loop and runner contracts plus high-level state | Preserve explicit interface boundaries without claiming a broad orchestrator exists yet | Why leave these as protocols? |
| Tool contracts | `src/tools/models.py`, `src/tools/base.py`, `src/tools/implementations/*` | Define risk levels, validated tool calls/results, and deterministic implementations | Keep tool boundaries typed and permission-aware | How are tool failures represented? |
| Verifier contracts | `src/verifiers/base.py`, `src/verifiers/implementations/*` | Define typed verifier requests/results and branch-aware verifier logic | Make verification first-class rather than implicit | Why not trust the tool output directly? |
| Transcript system | `src/transcripts/models.py`, `src/transcripts/writer.py` | Persist append-only JSONL execution history | Provide execution truth for replay, audit, and reconstruction | Why JSONL? Why append-only? |
| Checkpoint and memory | `src/memory/checkpoints.py`, `src/memory/incident_working_memory.py` | Persist control-plane checkpoints and semantic incident memory | Separate resume state from semantic understanding | What belongs in checkpoint vs working memory? |
| Permission system | `src/permissions/models.py`, `src/permissions/policy.py`, `src/permissions/classifier.py` | Produce structured allow/ask/deny decisions with provenance | Keep safety boundary explicit and inspectable | Why is the policy intentionally minimal? |
| Artifact reconstruction | `src/context/session_artifacts.py` | Rebuild latest usable artifacts from checkpoint + transcript | Centralize durable state lookup and failure/insufficiency handling | What happens when checkpoint and transcript disagree? |
| Handoff assembly | `src/context/handoff.py` | Assemble a readable operator-facing context from durable layers | Support deterministic handoff without making handoff the source of truth | How is precedence handled between checkpoint, artifact, and memory data? |
| Handoff persistence and regeneration | `src/context/handoff_artifact.py`, `src/context/handoff_regeneration.py` | Persist stable handoff JSON and rebuild it from a session id | Prove derived artifacts can be regenerated honestly from runtime state | Why return `insufficient` or `failed` instead of fabricating a handoff? |
| Shared harness and failure normalization | `src/runtime/harness.py`, `src/runtime/execution.py`, `src/runtime/models.py` | Centralize downstream step wiring and normalize synthetic failures | Reduce duplication while preserving explicit domain logic | What invariants are actually enforced here? |
| Skills | `src/skills/loader.py`, `src/skills/models.py`, `skills/incident-triage/SKILL.md` | Load durable skill assets with typed frontmatter | Keep the skill seam explicit and file-based | How much of the skill system is implemented today? |
| Replay/eval | `src/evals/incident_chain_replay.py`, `src/evals/models.py`, `tests/integration/test_incident_chain_replay_eval.py` | Replay fixed scenarios across the implemented chain | Turn runtime claims into deterministic test coverage | Why use replay scenarios instead of a generic benchmark harness? |

## 8. Likely Interview Questions And Strong Answer Outlines

### Basic Questions

#### 1. What did you build?

- A verifier-driven incident-response runtime in Python.
- It advances a narrow incident through typed slices from triage to approval-gated action stub.
- The interesting part is the runtime discipline: transcripts, checkpoints, verification,
  resumability, and handoff regeneration.

#### 2. What problem were you trying to solve?

- Not "how to make an AI answer incident questions."
- The real problem was how to make incident-oriented agent behavior durable, auditable, and safe.
- I wanted runtime contracts strong enough to explain in a systems interview.

#### 3. Why is this valuable even though it is narrow?

- Narrowness is a feature here.
- It let me make the state model and verifier contracts explicit.
- That makes the project more credible than a broad but weakly specified agent demo.

#### 4. What is the most important design idea in the project?

- Completion is verifier-driven, not model-driven.
- The system only advances when a verifier says the next state is justified.
- That changes the runtime from "prompt orchestration" into a real state machine.

### Architecture Questions

#### 5. Walk me through the step chain.

- Triage creates the first verified artifact.
- Follow-up selects one safe read-only investigation target.
- Evidence reads one deterministic bundle.
- Hypothesis creates one structured theory.
- Recommendation creates one structured next step.
- Action stub creates approval-aware action candidacy without execution.

#### 6. Why use append-only transcripts?

- They preserve ordered execution truth.
- They keep failures and retries visible instead of rewriting history.
- They support replay, audit, and artifact reconstruction cleanly.

#### 7. Why use checkpoints separately from transcripts?

- Checkpoints answer "where am I now?"
- Transcripts answer "what happened?"
- Keeping them separate prevents the control plane from becoming a copy of the full execution log.

#### 8. What is `SessionArtifactContext` solving?

- Repeated artifact reconstruction across resumable slices.
- It loads checkpoint + transcript once and exposes typed latest artifacts.
- It also surfaces insufficiency and synthetic failure instead of forcing each step to rediscover
  them.

#### 9. How do state transitions happen?

- A step runs.
- It records transcript events.
- It runs a verifier.
- It writes the next checkpoint phase only after verifier evaluation.

#### 10. Why not just store the latest artifact in the checkpoint?

- Because checkpoints are for control state, not full execution truth.
- Storing full artifact chains there would duplicate state and increase conflict risk.
- Reconstructing verified artifacts from transcripts is more auditable.

### Runtime And Reliability Questions

#### 11. What is a synthetic failure?

- A typed failure artifact created when the runtime expected a durable path and found something
  invalid or missing.
- Examples include invalid tool output, invalid verifier output, and missing verifier results.
- It keeps failure paths replayable and machine-readable.

#### 12. How is synthetic failure different from insufficiency?

- Insufficiency means "not ready yet" in a conservative sense.
- Synthetic failure means "the expected durable artifact chain is broken or malformed."
- Keeping them separate prevents the runtime from hiding real state corruption inside a vague
  no-op.

#### 13. How is resumability guaranteed?

- Each step writes a stable checkpoint and append-only transcript markers.
- Resume starts from durable files, not in-memory chat history.
- `SessionArtifactContext` reconstructs the latest usable verified artifact chain.

#### 14. What happens if the checkpoint says a recommendation exists but the transcript is missing
the verifier result?

- The context layer surfaces that as a structured synthetic failure.
- It does not silently trust the checkpoint.
- That is exactly the kind of conflict this architecture is designed to expose.

#### 15. What role does the shared harness play?

- It centralizes resume/start markers, tool execution, permission checks, verifier execution, and
  checkpoint writing.
- It reduces duplicated wiring across later slices.
- It does not absorb the domain logic or branch semantics of each slice.

### Memory Questions

#### 16. Why add `IncidentWorkingMemory` at all?

- To keep compact verified semantic understanding separate from checkpoint control state.
- It improves handoff-oriented context assembly.
- It avoids forcing every downstream consumer to scan the full transcript for high-level meaning.

#### 17. Why is working memory not the source of truth?

- Because mutable semantic memory can drift.
- Resume correctness should depend on checkpoints and verified transcript artifacts.
- Working memory is a supplement for context and handoff, not the authoritative execution record.

#### 18. What about project memory?

- It is intentionally deferred beyond minimal models.
- The current milestone proves only the first incident-working-memory slice.
- Cross-incident promotion would require freshness and governance rules that are out of scope here.

### Eval And Replay Questions

#### 19. Why does replay matter?

- It tests the architecture rather than just the prompt.
- It proves the runtime can carry state through deterministic branches.
- It makes conservative behavior testable, not just described in docs.

#### 20. What do the two replay scenarios prove?

- The supported path proves the runtime can justify a concrete action candidate.
- The conservative path proves the runtime can stop without manufacturing unjustified action.
- Together they show the runtime handles both confidence and uncertainty explicitly.

#### 21. Why use fixed fixtures instead of a broad benchmark harness?

- Because the goal is to validate runtime invariants, not chase benchmark breadth.
- Deterministic fixtures make state reconstruction and branch behavior easy to inspect.
- That is the right evaluation style for this milestone.

### Safety And Approval-Boundary Questions

#### 22. Why stop at an approval-gated action stub?

- Because a candidate and an execution are different safety problems.
- This milestone proves the runtime can reach the approval boundary honestly.
- It does not pretend that side-effecting execution is solved.

#### 23. How is approval represented?

- In structured checkpoint `approval_state`.
- The action-stub slice records whether approval would be required and why.
- The boundary is durable and inspectable instead of being implied in prompt text.

#### 24. Why is permission provenance important if the policy is simple?

- Because even a simple policy should be auditable.
- Provenance explains why the runtime allowed, asked, or denied.
- That becomes more valuable as the system evolves.

### Comparison And Tradeoff Questions

#### 25. Why not just use Claude Code?

- Because Claude Code is solving a broader coding-agent problem.
- This project is optimized for incident runtime guarantees like verifier-driven transitions,
  explicit approval state, and operator handoff regeneration.
- Borrowing its breadth would have made this repo less focused.

#### 26. Why not just use LangChain?

- The project goal was not to assemble a generic agent workflow quickly.
- The goal was to make runtime contracts explicit with typed models and durable artifacts.
- A framework could help with orchestration, but it would not replace the need for this repo's
  checkpoint, transcript, verifier, and failure-boundary design.

#### 27. Why no generic loop yet?

- The current explicit slices are easier to review, test, and explain.
- A generic loop would be the next level of abstraction, not the first one.
- I wanted stable invariants before broader orchestration.

#### 28. Why no multi-agent system?

- Multi-agent behavior would add coordination complexity before the single-runtime invariants are
  fully exploited.
- It would blur safety and ownership boundaries.
- It is outside the scope of a milestone focused on resumability and verification.

#### 29. What are the main limitations?

- No real execution or external integrations.
- Narrow deterministic incident coverage.
- Only the first semantic-memory slice is implemented.
- Stronger as a harness milestone than as a finished ops product.

#### 30. What are you most proud of architecturally?

- The separation of control state, execution truth, semantic memory, and handoff artifacts.
- `SessionArtifactContext` plus synthetic failure handling.
- The fact that the runtime stops honestly at the approval boundary.

## 9. Deep Technical Challenge Questions

### 1. What do you do if transcript truth and checkpoint truth conflict?

Strong answer:

- I treat the checkpoint as control-plane intent, not unquestioned execution truth.
- `SessionArtifactContext` checks whether the transcript-backed verified artifact chain actually
  supports the checkpoint phase.
- If it does not, the runtime surfaces insufficiency or synthetic failure instead of silently
  repairing history.

### 2. Why are transcripts append-only instead of mutable snapshots?

Strong answer:

- Append-only history preserves auditability and replay semantics.
- Mutable snapshots are fine for checkpoints or working memory, but not for execution truth.
- If you rewrite execution history, you make it harder to explain what actually happened and why.

### 3. How do you handle an interrupted step where a `tool_request` exists but no `tool_result`
exists?

Strong answer:

- That is exactly the kind of situation synthetic failure invariants are meant to represent.
- The runtime should expose the broken path as structured failure, not treat it as a clean no-op.
- That keeps resume logic honest and negative paths testable.

### 4. What could go wrong if `IncidentWorkingMemory` became too powerful?

Strong answer:

- It could start drifting away from transcript-backed truth.
- People might accidentally use it as the resume source of truth.
- That would make the system more convenient in the short term but less reliable and less
  explainable.

### 5. Why not use transcripts alone and skip checkpoints entirely?

Strong answer:

- You can reconstruct a lot from transcripts, but control-plane state becomes more expensive and
  ambiguous to derive repeatedly.
- Checkpoints give a stable, explicit answer to "what phase are we in now?"
- The combination of checkpoint + transcript is stronger than either layer alone.

### 6. How would you evolve this into a real operations agent?

Strong answer:

- First add explicit approval recording and safe execution semantics for a very narrow write path.
- Then add verifiers for real external effects and rollback expectations.
- Only after that would I broaden tool coverage or integration depth.

### 7. What should be built next and why?

Strong answer:

- The next logical step is not broad autonomy.
- It is a carefully scoped execution slice with explicit approval and post-action verification.
- That would extend the same design story instead of changing it.

### 8. Where are the current guarantees strongest, and where are they weakest?

Strong answer:

- Strongest in typed contracts, verifier-driven transitions, deterministic replay, and durable
  artifact reconstruction.
- Weakest in breadth, external execution semantics, and productized human workflows.
- That is acceptable because the project is intentionally a runtime milestone.

### 9. What is the hardest concept to explain to an interviewer?

Strong answer:

- Usually the difference between control-plane state, execution truth, semantic memory, and derived
  artifacts.
- Once that layering is clear, most of the other design choices make sense.
- I would explain it with checkpoints, transcripts, working memory, and handoff JSON as four
  different layers with different jobs.

### 10. What could go wrong if you skipped verifiers and trusted tools?

Strong answer:

- The runtime would move phases optimistically without justified state transitions.
- Failures would look like business logic bugs rather than explicit runtime contract failures.
- The whole project would become a thinner wrapper around tool calls instead of a verifier-driven
  harness.

## 10. Demo Guidance For Interviews

### The Two Key Demo Scenarios

#### Scenario A: Supported Path

Command:

```bash
pytest tests/integration/test_incident_chain_replay_eval.py::test_incident_chain_replay_eval_runs_supported_hypothesis_chain
```

What to highlight:

- follow-up target becomes `recent_deployment`
- hypothesis becomes `deployment_regression`
- recommendation becomes `validate_recent_deployment`
- action stub becomes `rollback_recent_deployment_candidate`

What to say:

"This is the branch where the runtime has enough evidence to justify a concrete action candidate,
but it still stops at the approval boundary instead of executing anything."

#### Scenario B: Conservative Path

Command:

```bash
pytest tests/integration/test_incident_chain_replay_eval.py::test_incident_chain_replay_eval_runs_insufficient_evidence_chain
```

What to highlight:

- follow-up target becomes `runbook`
- hypothesis becomes `insufficient_evidence`
- recommendation becomes `investigate_more`
- action stub becomes `no_actionable_stub_yet`

What to say:

"This is the branch that matters for safety. The runtime does not force a stronger claim than the
artifact chain supports."

### Files And Artifacts Worth Opening Live

- `tests/integration/test_incident_chain_replay_eval.py`
- `src/evals/incident_chain_replay.py`
- `evals/fixtures/incident_chain_recent_deployment.json`
- `evals/fixtures/incident_chain_insufficient_evidence.json`
- `src/context/session_artifacts.py`
- `src/runtime/harness.py`
- `src/context/handoff.py`
- `src/context/handoff_regeneration.py`

If you want to show persisted artifacts during a longer demo, also point at:

- `sessions/checkpoints/<session_id>.json`
- `sessions/transcripts/<session_id>.jsonl`
- `sessions/working_memory/<incident_id>.json`
- `sessions/handoffs/<incident_id>.json`

### How To Explain Supported vs Conservative Behavior

Use this contrast:

- supported path: the runtime can justify a specific candidate because the evidence and verifier
  chain are strong enough
- conservative path: the runtime deliberately preserves uncertainty and avoids manufacturing
  actionability

That contrast is one of the strongest signals in the whole project.

## 11. Resume And Application Alignment

### Strongest Technical Signals This Project Demonstrates

- runtime architecture and state modeling
- verifier-driven orchestration rather than prompt-only chaining
- append-only durable execution logs
- checkpoint-based resumability
- structured failure normalization
- explicit safety and permission boundaries
- artifact reconstruction and handoff regeneration
- deterministic replay/eval design

### Job Descriptions This Project Matches Best

Best fit:

- agent runtime engineering
- AI infrastructure / framework roles
- applied AI systems roles with reliability focus
- orchestration / workflow / evaluation platform roles
- backend-heavy agent engineering roles

### Job Descriptions It Matches Only Partially

Partial fit:

- end-user product roles that want rich UI or polished product flows
- general LLM application roles centered on chat UX
- full autonomous DevOps platform roles expecting real infra integrations
- data/ML roles that prioritize model training over runtime architecture

### How To Describe It For Runtime / Framework Roles

Emphasize:

- source-of-truth layering
- verifier-driven transitions
- synthetic failure handling
- checkpoint/transcript separation
- replayability
- approval boundaries

### How To Describe It For Application Roles

Emphasize:

- incident workflow support
- safe next-step generation
- operator handoff quality
- deterministic demos

But be honest that the repository is more runtime-focused than product-focused.

## 12. Honest Limitations

### What Is Intentionally Out Of Scope

- real execution or remediation
- approval UI or reviewer workflow integration
- multi-agent orchestration
- external service integrations
- broad planner / workflow engine behavior
- context compaction and productized memory systems

### What Is Not Yet Productized

- external approvals
- mutation semantics
- rollback support
- service integrations
- user-facing operational surfaces

### What The Next Logical Evolution Would Be

The next logical step is a very narrow, explicitly approved execution slice with verifier-backed
post-action validation. That would extend the current design story instead of changing it.

## Final Advice For Interviews

If an interviewer pushes toward breadth, pull the conversation back to the runtime question:

"The point of this project is not that it can do everything. The point is that the things it does
are verifier-driven, durable, resumable, auditable, and explicit about safety boundaries."

That is the central message of the repository.

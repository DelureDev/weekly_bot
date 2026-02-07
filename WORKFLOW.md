# Workflow Guide: Agents and Skills

This file explains how to work in this repository using the agent files in `.github` and installed Codex skills.

## 1) Default Working Loop

1. Define the task clearly:
   - Goal
   - Constraints
   - Affected files
   - Definition of done
2. Start with `Codex.agent.md` as orchestrator.
3. Route to one or more specialized agents only when needed.
4. Implement the smallest safe change.
5. Validate (`py_compile`, behavior check).
6. Update docs if behavior/config changed.

Recommended validation command:

```powershell
py -3 -m py_compile weekly_report.py test_gsheets.py test_telegram.py
```

## 2) Which Agent To Use

- `Codex.agent.md`: default entry point and routing.
- `TechLead.agent.md`: scope, risks, acceptance criteria, implementation plan.
- `BackendDeveloper.agent.md`: Python implementation and refactoring.
- `TelegramConversation.agent.md`: Telegram command UX and flow safety.
- `QATest.agent.md`: regression checks and behavior validation.
- `Security.agent.md`: security checks (secrets, access control, input handling).
- `DevOpsRelease.agent.md`: environment config and runtime/release readiness.
- `Documentation.agent.md`: sync docs with code behavior.

## 3) Which Skill To Use

Use skills only when the task matches the skill scope.

- `gh-fix-ci`: inspect and fix failing GitHub Actions checks.
- `gh-address-comments`: address open PR review comments.
- `security-best-practices`: explicit secure-coding review request.
- `security-threat-model`: explicit threat-modeling request.
- `create-plan`: when you explicitly want a concise plan.
- `codex-readiness-unit-test`: readiness unit-style report.
- `codex-readiness-integration-test`: end-to-end readiness integration loop.
- `doc`: `.docx` creation/editing tasks.

## 4) Recommended Sequences

### New Feature
1. `TechLead` -> define scope and acceptance criteria.
2. `BackendDeveloper` (and `TelegramConversation` if command UX changes).
3. `QATest`.
4. `Security` (if auth/input/output touched).
5. `Documentation`.

### Bug Fix
1. `BackendDeveloper` (minimal fix).
2. `QATest` (repro + regression).
3. `Documentation` (if user-visible behavior changed).

### Security Review
1. `Security.agent.md`.
2. Skill: `security-best-practices` (or `security-threat-model` if threat modeling is requested).

## 5) Team Conventions

- Keep changes narrow and reversible.
- Do not commit secrets (`.env`, tokens, service account keys).
- Preserve critical bot invariants:
  - `BOT_TOKEN` and `SPREADSHEET_ID` are mandatory.
  - `/otchet` must return readable errors on failures.
  - Scheduled report must not run when `REPORT_CHAT_ID` is missing/invalid.
  - HTML output must remain escaped and safe.
- Update docs in the same change when behavior or configuration changes.

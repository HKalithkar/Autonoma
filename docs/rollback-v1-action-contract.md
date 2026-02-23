# Codex Session Guide: Roll Back v1 Action Execution Schemas

Goal: revert the repo to the pre-v1 action execution contract state (remove v1 schemas, OpenAPI components, and contract tests) and leave the system aligned with the current API/DB schema.

## Scope of rollback
Remove the following artifacts introduced for AUT-0.1 v1 contracts:
- `contracts/action/v1/` (all v1 schema files)
- `contracts/openapi/action_execution_components.yaml`
- `apps/contracts/tests/test_action_contracts_v1.py`
- `docs/contracts/action-execution.md`
- README entry for the action execution contract doc

If you only want a partial rollback (e.g., keep schemas but remove tests), adjust the steps below.

## Step-by-step (Codex session)
1) Restate goal in 1–3 lines and identify impacted modules (contracts, tests, docs).
2) List the files to delete and the README line to remove (see Scope).
3) Implement changes:
   - Delete `contracts/action/v1/` directory.
   - Delete `contracts/openapi/action_execution_components.yaml`.
   - Delete `apps/contracts/tests/test_action_contracts_v1.py`.
   - Delete `docs/contracts/action-execution.md`.
   - Remove the `docs/contracts/action-execution.md` entry from `README.md`.
4) Verify (optional but recommended):
   - `make lint`
   - `make test`
5) Review checklist:
   - Ensure no references remain to v1 action execution contract in docs.
   - Confirm no tests reference deleted schemas.
   - Confirm OpenAPI components file is removed or not referenced elsewhere.

## Quick command sequence
```sh
rm -rf contracts/action/v1
rm -f contracts/openapi/action_execution_components.yaml
rm -f apps/contracts/tests/test_action_contracts_v1.py
rm -f docs/contracts/action-execution.md
# Edit README.md to remove the action-execution doc entry
```

## Notes
- This rollback does not alter any API/DB schema, since those were not updated to v1.
- If additional references to v1 contracts are added later, locate and remove them via:
  `rg -n "action execution contract|action_execution_components|contracts/action/v1" docs README.md apps`

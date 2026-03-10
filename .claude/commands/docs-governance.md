# Docs Governance

## Purpose and Guardrails

- Keep `docs/` and subfolders current with the codebase, except `docs/legacy/`.
- Keep archival changes explicit, reversible, and traceable.
- Preserve historical files in `docs/legacy/`; do not rewrite history unless content is factually wrong.
- Keep policy-level rules in `CLAUDE.md`; keep operational procedure in this command and references.

## Standard Workflow

1. Identify changed code scope and enumerate impacted docs.
2. Update active docs in `docs/` first.
3. Decide archival status for superseded or non-operational documents.
4. If archiving, move file under `docs/legacy/` while preserving filename and topical grouping.
5. Add or validate required front matter for every legacy file.
6. Run quick checks for policy coverage and archive metadata.
7. Include docs verification output in issue/PR notes.

For the detailed command-level procedure, read `.agents/skills/docs-governance/references/workflow.md`.

## Archive Decision Rules

- Archive a document when it is superseded by a newer operational doc.
- Archive a document when it is no longer operationally used.
- Keep a document in active `docs/` when it is still an operational source of truth.
- Use `archive_reason` values exactly:
  - `superseded`
  - `no_longer_operational`
  - `historical_reference`

For valid and invalid front matter examples, read `.agents/skills/docs-governance/references/archive-frontmatter.md`.

## Front Matter Rule Enforcement

For every file in `docs/legacy/`, require YAML front matter keys:

- `archived_on`
- `archive_reason`
- `replaced_by`

Enforce relation constraints:

- `replaced_by` is required when `archive_reason: superseded`.
- `replaced_by` is optional otherwise.

## Verification

Pre-PR checklist:

- Active docs in `docs/` reflect the current implementation.
- No unrelated doc rewrites were introduced.
- Legacy files retain original filenames and grouping.
- Every `docs/legacy/` file has required front matter keys.
- `replaced_by` is non-null when `archive_reason: superseded`.
- `CLAUDE.md` keeps hard policy constraints.

Verification commands:

```bash
rg -n "docs-governance|archive_reason|replaced_by|docs/legacy" CLAUDE.md .agents/skills/docs-governance/SKILL.md .agents/skills/docs-governance/references/*.md
```

```bash
rg -n "^---$|archived_on|archive_reason|replaced_by" docs/legacy/*.md
```

For the full checklist, read `.agents/skills/docs-governance/references/checklist.md`.

# Development Notes

Use this file as your learning log in each iteration.

## Template

### Date

- YYYY-MM-DD

### Goal

- What we tried to build

### Concepts Learned

- Concept 1:
- Concept 2:

### Code Locations

- `path/to/file.py`: what this file is responsible for

### Common Pitfalls

- Pitfall:
- How to avoid:

### Self-Test Checklist

- Can run locally
- Core flow works
- Error case tested

### Reflection

- What I understand now:
- What remains unclear:

## Iteration 1 (MVP foundation)

### Date

- 2026-04-03

### Goal

- Build a runnable Insight foundation with block management, record CRUD, overlap support, and base dashboard.

### Concepts Learned

- Layered architecture: `ui -> services -> storage -> domain`.
- Why overlap support is a data-model decision, not just a UI decision.

### Code Locations

- `src/app/ui/main_window.py`: left-nav shell and page composition.
- `src/app/ui/record_page.py`: manual/timer record flow, inline block creation, recent block reuse.
- `src/app/ui/blocks_page.py`: block CRUD with soft-disable.
- `src/app/ui/stats_page.py`: 7/30 day charts and block summary table.
- `src/app/storage/repositories.py`: concrete DB operations for blocks/records.
- `src/app/services/analytics_service.py`: daily time-series aggregation.

### Common Pitfalls

- Pitfall: validating score range only in UI.
- How to avoid: enforce validation in service layer (`record_service.py`) too.
- Pitfall: trying to block overlapped records.
- How to avoid: preserve overlap by design and aggregate by `block_id`.

### Self-Test Checklist

- Can run locally
- Core flow works
- Error case tested

### Reflection

- What I understand now: MVP success depends on low-friction input and stable data contracts.
- What remains unclear: next step is deciding how to present correlations without implying false causality.

## Iteration 2 (Timeline + Stats UX refinement)

### Date

- 2026-04-03

### Goal

- Refine the recording UX around a week timeline and improve chart readability/usability.

### Concepts Learned

- Relative import behavior differs between `python -m package.module` and direct script execution.
- For desktop apps, packaging should be the final step after feature stabilization.

### Code Locations

- `src/app/ui/week_timeline_widget.py`: custom timeline painting, selection, label collision handling.
- `src/app/ui/record_page.py`: context-menu driven create/edit flow and compact dialog editing.
- `src/app/ui/stats_page.py`: category overview charts, custom chart persistence and cleanup actions.
- `src/app/storage/database.py`: schema evolution and default block initialization.

### Common Pitfalls

- Pitfall: testing packaging before entrypoint strategy is stable.
- How to avoid: keep dev run path fixed (`python -m src.app.main`), package at release stage.
- Pitfall: over-cleaning project files during troubleshooting.
- How to avoid: only remove generated artifacts (`build/dist/spec/temp entrypoints`).

### Self-Test Checklist

- Timeline interaction works
- Record/edit dialog flow works
- Stats overview + custom charts work
- Packaging artifacts cleaned without touching source files

### Reflection

- What I understand now: stable architecture and UX first, packaging second.
- What remains unclear: final release checklist and installer strategy for end users.
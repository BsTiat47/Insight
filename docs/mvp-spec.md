# Insight MVP Specification (Windows)

## 1) Goal

Insight is a Windows desktop app for low-friction activity logging and block-based statistics.
Users define event blocks first, then log records by selecting a block and entering time + score.

## 2) Data Contract (Frozen)

### Table: `event_blocks`

- `id` (int, primary key)
- `name` (string, unique, required)
- `color` (string, required, hex like `#3B82F6`)
- `is_active` (bool, default true)
- `created_at` (datetime, required)
- `updated_at` (datetime, required)

### Table: `activity_records`

- `id` (int, primary key)
- `block_id` (int, FK -> `event_blocks.id`, required)
- `start_time` (datetime, required)
- `end_time` (datetime, required, must be later than `start_time`)
- `efficiency_score` (int, 1-5, required)
- `state_score` (int, 1-5, optional)
- `tags` (string, optional)
- `note` (text, optional)
- `created_at` (datetime, required)
- `updated_at` (datetime, required)

## 3) Overlap Rule

- Overlap is allowed by design.
- Multiple records can exist in the same time period.
- No conflict check blocks insert/update.
- Each overlapped record has independent score and independent aggregation.

## 4) Statistics Contract

- Frequency = number of records.
- Duration = sum of each record duration in minutes.
- Block-level stats aggregate by `block_id`.
- MVP does not deduplicate overlapped durations.
- Dashboard ranges: last 7 days and last 30 days.

## 5) GUI Contract (MVP)

- Left navigation with pages: `记录` / `统计` / `方块管理` / `设置`.
- `方块管理`: create/edit/enable/disable blocks.
- `记录`: manual mode and timer mode.
- `记录`: allow inline block creation when block is missing.
- `统计`: 3 base charts (frequency, avg efficiency, avg state) + block summary table.

## 6) Scoring Rubric

### Efficiency (`efficiency_score`, required)

- `1`: almost no useful progress
- `2`: low progress
- `3`: normal progress
- `4`: high progress
- `5`: major progress

### State (`state_score`, optional)

- `1`: very poor condition
- `2`: poor condition
- `3`: neutral baseline
- `4`: good condition
- `5`: excellent condition

## 7) MVP Acceptance

- Create 3 records within 1 minute.
- Data persists after restart.
- Dashboard shows 7/30 day trends.
- Windows packaging instructions are available.

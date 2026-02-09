# Article -> Unit -> Structure Dataset

This directory contains the released dataset snapshot used by the benchmark (self-contained JSON).

Files:
- `normbench_v1.json`

Format (high level):
- The top-level is a JSON object with keys like `dataset_id/format_version/created_at/schema/stats/items/...`.
- `items` is a list. Each item contains:
  - `input`: `{rule_id, law_title, article_number, rule_text, full_article_text}`
  - `gold.units`: gold unit segmentation and the corresponding `st2.v3` SG-DT annotations (minimal field set)

`gold.units[*]` (min_unit) fields:
- `unit_id`: `"U1"`, `"U2"`, ...
- `unit_text`
- `unit_reason`
- `branches`: `st2.v3.branches`
- `meta`: `st2.v3.meta`

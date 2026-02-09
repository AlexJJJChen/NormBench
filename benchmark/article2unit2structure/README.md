# Article -> Unit -> Structure (One-call Experiment)

Goal: complete both steps in **one** LLM call:
1) Article -> executable units (unit segmentation)
2) For each unit -> `st2.v3` structured output

The runner stores:
- `stage1/units.json`: units derived from the model output (for analysis)
- `stage1/structured_units.json`: unit-level structured outputs (used by evaluation)
- `stage1/checkpoints/*.json`: full prompts + raw model outputs + parsed objects

## Run

```bash
python -m benchmark.article2unit2structure run \
  --batch demo \
  --model-alias local-vllm \
  --resume
```

## Evaluate

```bash
python -m benchmark.article2unit2structure evaluate \
  --run-dir benchmark/article2unit2structure/runs/<batch_id>
```

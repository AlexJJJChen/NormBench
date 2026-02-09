# NormBench

NormBench is a reproducible benchmark repository for **normative scope parsing and compilation**.
Each item is annotated with a **Span-Grounded Deontic Tree (SG-DT)**.

This repo contains:
- `benchmark/`: runnable code (inference + evaluation)
- `dataset/`: released dataset snapshots used by the benchmark

## Install

```bash
cd NormBench
python -m pip install -r requirements.txt
```

## Model Configuration

NormBench uses the OpenAI Python SDK to call **OpenAI-compatible** chat completion endpoints (OpenAI, vLLM, and compatible gateways).

1) Create your model routing config:
```bash
cp benchmark/models.example.json benchmark/models.json
```

2) Configure environment variables (CLI auto-loads repo-root `.env`):
```bash
cp .env.example .env
```

3) Edit:
- `.env`: set `NORMBENCH_MODEL_CONFIG` and provider-level `*_BASE_URL` / `*_API_KEY`
- `benchmark/models.json`: map **model aliases** to routing configs (`type/model/provider/api_base_env/api_key_env`)

Notes:
- Env var names only need to distinguish providers. The alias-to-provider mapping is a manual mapping in `benchmark/models.json`.
- Each model alias can use a different provider (different base URL and key).

Example entry in `benchmark/models.json`:
```json
{
  "models": {
    "deepseek-chat": {
      "type": "llm_api",
      "model": "deepseek-chat",
      "api_base_env": "DEEPSEEK_BASE_URL",
      "api_key_env": "DEEPSEEK_API_KEY",
      "provider": "deepseek-ai"
    }
  }
}
```

## Run Inference

The default dataset snapshot is shipped at `dataset/article2unit2structure/normbench_v1.json`.
It contains 2,290 provision-language items.

```bash
python -m benchmark.article2unit2structure run \
  --batch demo \
  --model-alias deepseek-chat \
  --limit 10 \
  --max-concurrency 10
```

`--batch` automatically appends a timestamp suffix. The run directory looks like:
- `benchmark/article2unit2structure/runs/demo_YYYYMMDD_HHMMSS/`

Main outputs:
- `benchmark/article2unit2structure/runs/<run_id>/stage1/structured_units.json` (predicted SG-DT in JSON)

Other helpful files under `.../stage1/`:
- `units.json`: extracted units derived from model outputs
- `summary.json`: small run summary
- `checkpoints/*.json`: per-item prompts + raw responses + parsed objects

## Run Evaluation

```bash
python -m benchmark.article2unit2structure evaluate \
  --run-dir benchmark/article2unit2structure/runs/<run_id> \
  --dataset dataset/article2unit2structure/normbench_v1.json
```

Evaluation outputs (under `--run-dir/evaluation/` by default):
- `metrics.json`: compact headline metrics
- `metrics_full.json`: full export (counts, rates, settings, etc.)
- `per_sample.jsonl`: per-sample details (for debugging/analysis)

The evaluator also writes a schema-fixed copy of predictions to:
- `stage1/structured_units_fixed.json`

All run artifacts live under:
- `benchmark/article2unit2structure/runs/<run_id>/`

## Notes

- This repository does not ship any private API keys. Put keys in `.env` (not in `benchmark/models.json`).
- If you do not want to set `NORMBENCH_MODEL_CONFIG` in `.env`, you can pass it explicitly:
  `--model-config benchmark/models.json`

## License

This project is licensed under the Creative Commons Attribution 4.0 International (CC BY 4.0).
See `LICENSE` for details.

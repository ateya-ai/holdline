# Evaluating model explanations

The model writes a summary of already validated findings. A well-formed response can still be wrong. Evaluate wording separately from the deterministic rules.

## Offline checks

```bash
python -m pytest tests/test_model.py -ra
```

These checks use fake model clients. They prove rehearsal does not construct a provider client, evidence reaches the adapter, optional tracing does not gate the model configuration, and provider failures or release claims produce the labelled fallback.

## Optional provider evaluation

Start a configured stack and export its access token. Then run:

```bash
python scripts/evaluate_live.py --allow-paid
```

This explicitly permits four live requests, one per fixture. It records the model name, review IDs, skill hashes, findings, source snapshots, and explanation source in a local JSON report. The provider may charge for these calls. No paid provider evaluation is performed by CI.

Review each explanation against this rubric:

| Criterion | Accept when |
| --- | --- |
| Grounding | Every stated cause appears in the stored findings |
| Agreement | The wording agrees with the deterministic disposition |
| Release boundary | It does not imply stock was released or a person approved it |
| Missing evidence | An incomplete review acknowledges the missing evidence |
| Clarity | A receiving clerk can understand the explanation without reading implementation names |

Do not mark a fallback as a successful model response. Investigate repeated fallbacks as configuration, provider, or wording failures. Record provider usage or cost from the provider/trace interface; the evaluation script does not invent a cost estimate.

Add new synthetic cases when a wording failure is found. Keep regression cases free of real shipment or personal data. Re-evaluate when changing the model, prompt, or evidence format.

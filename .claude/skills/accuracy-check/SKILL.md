---
name: accuracy-check
description: Run the Lemely accuracy harness and golden-mark fixtures against the deterministic parser, then summarise pass/fail with mark deltas for any mismatches.
disable-model-invocation: true
---

Activate the venv and run the accuracy / golden test suite:

```bash
source /home/sico/Code/Lemely/.venv/bin/activate && \
  cd /home/sico/Code/Lemely && \
  pytest tests/accuracy/ tests/golden/ tests/test_parsers_det.py \
    -v --tb=short 2>&1 | tail -80
```

Then report:
- Total passed / failed / errored
- For any MISMATCH: the paper name, computed total vs expected total, and which questions differ
- The first full traceback if any test raised an exception
- Overall verdict: PASS (all green) or FAIL (with count)

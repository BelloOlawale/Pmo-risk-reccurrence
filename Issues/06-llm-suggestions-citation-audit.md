# 06: LLM Risk Suggestions + Grounded Citation Audit

- **Type:** AFK
- **Spec:** SPEC.md §7
- **Blocked by:** #04, #05
- **Port from:** `../risk_reccurrence_predictor/src/llm/{openai_client,prompts,citations,evaluation}.py`

## What to build

The suggestion endpoint end-to-end.

1. Port `openai_client.py` (Azure OpenAI GPT-4o-mini chat) and `prompts.py` (system prompt: risk-landscape overview + per-risk analysis + recommendations).
2. Port `citations.py` (linkify `[RiskID, file.xlsx]` → clickable source URLs) and `evaluation.py` (post-LLM citation audit + groundedness score).
3. `POST /api/suggest` service:
   - load project context (department + type),
   - run hybrid retrieval (exact #04 + keyword + semantic #05),
   - call LLM with the retrieved candidates,
   - audit citations against the payload, compute groundedness,
   - return JSON: overview, per-risk analysis, suggested risks, evaluation metadata.

## Acceptance criteria

- [ ] `POST /api/suggest` returns a landscape overview + ranked suggested risks
- [ ] Every suggested risk has a grounded citation to a source file (or `[unverified]` marker)
- [ ] Citations link to the source file URL
- [ ] Groundedness score returned in the payload
- [ ] Unit tests for prompts, citation linkification, and audit (ported + adapted)

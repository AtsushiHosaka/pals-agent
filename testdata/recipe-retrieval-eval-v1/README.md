# Recipe retrieval scale evaluation

`corpus.json` holds paraphrase positives and near-variant negatives for measuring semantic Recipe
reuse at several catalog sizes. A separate author wrote them from the English statement and Lean
target, without seeing the ranker or the Japanese catalog statement. `hard` positives deliberately
avoid textbook vocabulary. Negative labels are author intent, so every false reuse is reviewed by
hand before it is reported as a real one.

`evaluate.py` runs the production `attempt()` path with real judges over a retrieved window. Catalog
cards are read-only input and are not copied here.

```sh
PYTHONPATH=. OPENAI_API_KEY=... python testdata/recipe-retrieval-eval-v1/evaluate.py \
  --cards "$TEXTBOOK_CATALOG_DIRECTORY" --output "$NEW_PRIVATE_RESULT_FILE" \
  --vector-cache "$PRIVATE_VECTOR_CACHE_FILE"
```

The run calls paid providers and appends one JSON line per query, so it can resume. Results are
recorded in the parent repository under `docs/recipe-retrieval-scale-2026-11-02.md`.

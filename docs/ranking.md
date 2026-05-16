# Recall Ranking Strategy

Recall uses hybrid retrieval:

1. `FTS5` for OCR text, filename, and path matches
2. `FAISS` for semantic similarity when available
3. A local fallback vector scorer when FAISS is not installed

## Weighting

Default query blend:

- `0.65 semantic`
- `0.30 text`
- `0.05 recency`

Exact-looking queries, quoted strings, or filename-shaped queries shift toward text-heavy weighting:

- `0.45 semantic`
- `0.50 text`
- `0.05 recency`

## Candidate generation

- Up to `200` FTS candidates
- Up to `200` semantic candidates
- Dedupe by image id
- Merge with normalized rank-position scoring

## Result shaping

- `relevance` sorts by final blended score
- `newest` sorts by file modification time descending
- `oldest` sorts by file modification time ascending

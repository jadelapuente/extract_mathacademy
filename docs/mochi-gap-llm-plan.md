# Mochi Gap LLM Integration Plan

`data/mochi-gap-inputs.json` is a compact registry plus a list of lightweight
LLM work units:

```json
{
  "gap_groups": [
    {
      "id": "inverses-of-2x2-matrices",
      "name": "Inverses of 2x2 Matrices",
      "target_topics": [
        {
          "id": 864,
          "name": "Inverses of 2x2 Matrices",
          "placements": [
            {
              "course_id": 136,
              "course_name": "Mathematical Foundations III",
              "section_id": 524,
              "section_name": "Matrices",
              "subsection_id": 96010,
              "subsection_name": "Matrix Inverses"
            }
          ]
        }
      ],
      "context_topics": [
        {
          "id": 865,
          "name": "Using Inverses to Solve Matrix Equations",
          "placements": [],
          "relation": "child",
          "source_topic_id": 864
        }
      ],
      "missing_topic_ids": []
    }
  ],
  "mochi_decks": [
    {
      "id": "IUHYijBy",
      "name": "Matrices",
      "parent_id": "Ws4sMhQh",
      "path": "Math / Matrices"
    }
  ],
  "llm_deck_judging_units": [
    {
      "gap_group_id": "inverses-of-2x2-matrices",
      "candidate_deck_ids": ["IUHYijBy"]
    }
  ]
}
```

The application should materialize the actual LLM payload at runtime by joining
one `llm_deck_judging_units` entry to its `gap_groups` and `mochi_decks` records:

```json
{
  "task": "select_relevant_mochi_decks",
  "gap_group": {
    "id": "inverses-of-2x2-matrices",
    "name": "Inverses of 2x2 Matrices",
    "target_topics": [],
    "context_topics": []
  },
  "candidate_decks": []
}
```

The expected judge output should be strict JSON:

```json
{
  "gap_group_id": "inverses-of-2x2-matrices",
  "relevant_decks": [
    {
      "deck_id": "IUHYijBy",
      "confidence": 0.93,
      "reason": "Matches matrix inverse target topics."
    }
  ]
}
```

Use an adapter boundary so the model/provider can be swapped later:

```python
def judge_relevant_decks(gap_group, candidate_decks) -> list[DeckJudgment]:
    ...
```

For a single downloaded topic, use the same shape. A topic URL such as
`https://mathacademy.com/topics/153` becomes one gap group:

```json
{
  "gap_groups": [
    {
      "id": "topic-153",
      "name": "The Determinant of a 3x3 Matrix",
      "target_topics": [
        {
          "id": 153,
          "name": "The Determinant of a 3x3 Matrix",
          "placements": [
            {
              "course_id": 136,
              "course_name": "Mathematical Foundations III",
              "section_id": 1068,
              "section_name": "Linear Algebra",
              "subsection_id": 123416,
              "subsection_name": "Determinants"
            }
          ]
        }
      ],
      "context_topics": [
        {
          "id": 863,
          "name": "Introduction to the Inverse of a Matrix",
          "placements": [],
          "relation": "next",
          "source_topic_id": 153
        }
      ],
      "missing_topic_ids": []
    }
  ],
  "llm_deck_judging_units": [
    {
      "gap_group_id": "topic-153",
      "candidate_deck_ids": ["IUHYijBy"]
    }
  ]
}
```

The only semantic difference is cardinality: a single-topic extraction has one
target topic, while a completed-topic date range may have many target topics per
group. Downstream deck judging, card fetching, and gap analysis should treat
both as the same interface.

Recommended cheap OSS candidates to evaluate are Qwen3 14B/30B class models,
Llama 3.1/3.3 8B or 70B depending on cost and latency, and Mistral
Small/Ministral class models where available. Prefer an OpenAI-compatible local
or hosted route, but do not hardcode the provider into the data-prep script.

Batching guidance:

- Start with one LLM call per gap group plus all candidate deck names/paths.
- Batch several small gap groups only when the combined context is comfortably
  small.
- Use deterministic settings, with temperature near 0.
- Require strict JSON output and validate it before any later card-fetching
  stage consumes it.
- Cache judgments by a hash of the materialized gap group plus deck inventory.

Guardrails:

- Later card-fetching and card-generation stages must derive allowed topic IDs
  only from `gap_group.target_topics[*].id`.
- Context topics can explain why a deck is relevant, but cannot authorize card
  creation.

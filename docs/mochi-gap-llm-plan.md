# Mochi Gap LLM Integration Plan

`data/mochi-gap-inputs.json` is the LLM-facing gap-analysis input. It keeps only
the topic names/IDs needed for judging and the shared Math deck list needed for
card fetching:

```json
{
  "gap_groups": [
    {
      "id": "solving-quadratic-inequalities",
      "name": "Solving Quadratic Inequalities",
      "target_topics": [
        {
          "id": 468,
          "name": "Solving Quadratic Inequalities"
        },
        {
          "id": 3833,
          "name": "Quadratic Inequalities"
        }
      ],
      "context_topics": [
        {
          "id": 469,
          "name": "Solving Polynomial Inequalities",
          "relation": "child",
          "source_topic_id": 468
        }
      ],
      "missing_topic_ids": []
    }
  ],
  "all_math_decks": [
    {
      "id": "GTfQjkXd",
      "name": "Math / Algebra / Functions / Quadratics & Parabolas"
    }
  ]
}
```

Runtime LLM payload:

```json
{
  "task": "find_mochi_card_gaps",
  "gap_group": {
    "id": "solving-quadratic-inequalities",
    "name": "Solving Quadratic Inequalities",
    "target_topics": [],
    "context_topics": [],
    "missing_topic_ids": []
  },
  "candidate_decks": [
    {
      "id": "GTfQjkXd",
      "name": "Math / Algebra / Functions / Quadratics & Parabolas"
    }
  ]
}
```

For a single downloaded topic, use the same shape with one target topic:

```json
{
  "gap_groups": [
    {
      "id": "topic-153",
      "name": "The Determinant of a 3x3 Matrix",
      "target_topics": [
        {
          "id": 153,
          "name": "The Determinant of a 3x3 Matrix"
        }
      ],
      "context_topics": [
        {
          "id": 863,
          "name": "Introduction to the Inverse of a Matrix",
          "relation": "next",
          "source_topic_id": 153
        }
      ],
      "missing_topic_ids": []
    }
  ],
  "all_math_decks": [
    {
      "id": "GTfQjkXd",
      "name": "Math / Algebra / Functions / Quadratics & Parabolas"
    }
  ]
}
```

The expected LLM output should be strict JSON:

```json
{
  "gap_group_id": "solving-quadratic-inequalities",
  "relevant_decks": [
    {
      "deck_id": "GTfQjkXd",
      "confidence": 0.93,
      "reason": "Matches quadratic inequality target topics."
    }
  ]
}
```

Use an adapter boundary so the model/provider can be swapped later:

```python
def judge_relevant_decks(gap_group, candidate_decks) -> list[DeckJudgment]:
    ...
```

Recommended cheap OSS candidates to evaluate are Qwen3 14B/30B class models,
Llama 3.1/3.3 8B or 70B depending on cost and latency, and Mistral
Small/Ministral class models where available. Prefer an OpenAI-compatible local
or hosted route, but do not hardcode the provider into the data-prep script.

Batching guidance:

- Start with one LLM call per gap group plus `all_math_decks`.
- Batch several small gap groups only when the combined context is comfortably
  small.
- Use deterministic settings, with temperature near 0.
- Require strict JSON output and validate it before any later card-fetching
  stage consumes it.
- Cache judgments by a hash of the gap group plus the deck inventory.

Guardrails:

- Later card-fetching and card-generation stages must derive allowed topic IDs
  only from `gap_group.target_topics[*].id`.
- Context topics can explain why a deck is relevant, but cannot authorize card
  creation.

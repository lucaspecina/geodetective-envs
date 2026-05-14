"""Prompts para el judge (annotator CORRAL-adapted).

Stage 1: extracción de nodos H/T/E/J/U/C con grounding (msg_idx + quote).
Stage 2: extracción de edges entre nodos, con quote support.

Diseño post-CORRAL replicación (`research/synthesis/process_eval_design.md`).
Definiciones operativas adaptadas a geo-detective.
"""

STAGE1_SYSTEM = """You are a careful annotator of agentic reasoning traces.

Your job: extract epistemic nodes from a geo-detective agent trace. The agent receives a historical photograph and tries to determine WHERE (lat/lon) and WHEN (year) it was taken using investigative tools.

You MUST only extract information explicitly present in the provided trace text.
You MUST include verbatim quotes that ground each node to a specific [MSG N] block.
Output strict JSON only.
"""

STAGE1_USER_TEMPLATE = """## Node types to extract

Each node is one of:

- **H** (Hypothesis): a revisable claim about the photo's location, time, or identifiable features. Examples: "this is a Russian provincial town", "the kostel on the left suggests Belarus", "year around 1900-1920".
- **T** (Test): a tool call invoked to probe a hypothesis. The tool call event itself is the test. Example: `web_search(query="Tomsk kostel")` is a T for the H "this is Tomsk".
- **E** (Evidence): observed input or output. The target photo and crops are E (modality: visual_primary / visual_crop). Tool results are E (modality: textual / coords / osm_feature / visual).
- **J** (Judgment): qualitative inference made by the agent. Example: "the result confirms Tomsk", "this image doesn't match", "the architecture suggests Imperial Russia".
- **U** (Update): explicit revision of a prior belief. The agent abandons or modifies an H. Example: "I was wrong about Tobolsk — switching to Tomsk".
- **C** (Commitment): a decision treated as settled, including `submit_answer` invocation (C with terminal=true). Sub-commitments mid-trace are also C (non-terminal).

## Output format (strict JSON)

```json
{
  "nodes": [
    {
      "node_id": "N1",
      "type": "H" | "T" | "E" | "J" | "U" | "C",
      "modality": "textual" | "visual_primary" | "visual_crop" | "coords" | "osm_feature" | null,
      "time": <msg_idx integer>,
      "terminal": true | false,
      "text": "<normalized short description, 1 sentence>",
      "support": [
        {"msg_idx": <int>, "quote": "<exact verbatim substring from the trace>"}
      ]
    }
  ]
}
```

## Rules

- node_id sequential N1, N2, N3, ...
- `time` = msg_idx of the [MSG N] block where the node first appears.
- `terminal` only applies to C nodes (true if it's a submit_answer call, false otherwise). For other types, set `terminal: false`.
- `modality` only applies to E nodes. For others, set `modality: null`.
- Every node MUST have at least one `support` entry with a verbatim quote.
- Do NOT invent nodes. If the agent didn't verbalize a hypothesis, do NOT extract H.
- An evidence E from a tool result counts even if the agent didn't comment on it explicitly.

## Trace to annotate

```
{trace_text}
```

Reply with strict JSON only. No commentary."""


STAGE2_SYSTEM = """You are a careful annotator of epistemic edges in an agentic reasoning trace.

You receive: (a) the original trace, (b) the set of nodes extracted in Stage 1.
Your job: identify edges between nodes that are supported by explicit text.

You MUST only add edges supported by explicit text in the trace.
You MUST include verbatim quotes for each edge.
Output strict JSON only.
"""

STAGE2_USER_TEMPLATE = """## Edge types

Each edge has a source node, destination node, relation, and quote support:

- **testing** (H → T): the Test directly addresses the Hypothesis' claim, attempts to verify or falsify it.
- **observing** (T → E): the Test produced this Evidence.
- **informs** (E → H, E → J): the Evidence provides information that informs a Hypothesis or Judgment.
- **contradicting** (E → H, E → J): the Evidence is inconsistent with a Hypothesis or Judgment.
- **competing** (H ↔ H): two Hypotheses are considered as rivals under the same evidence.
- **updating** (U → H): the Update transforms a prior H into a new H. The new H should also exist as a node.

## Output format (strict JSON)

```json
{
  "edges": [
    {
      "src": "<node_id>",
      "dst": "<node_id>",
      "relation": "testing" | "observing" | "informs" | "contradicting" | "competing" | "updating",
      "time": <msg_idx integer>,
      "support": [
        {"msg_idx": <int>, "quote": "<exact verbatim substring>"}
      ]
    }
  ]
}
```

## Rules

- `time` = msg_idx where the relationship is established.
- Only add edges with at least one supporting verbatim quote.
- Combinations of (src.type, dst.type, relation) must be valid:
  - testing: H → T
  - observing: T → E
  - informs / contradicting: E → {H, J}
  - competing: H ↔ H (symmetric, but emit once with src < dst by node_id)
  - updating: U → H

## Nodes (from Stage 1)

```json
{nodes_json}
```

## Trace to annotate

```
{trace_text}
```

Reply with strict JSON only. No commentary."""

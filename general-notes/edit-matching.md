# LLM Agentic File Editing — Context Matching Notes

## Problem

When an LLM agent edits a file using a diff/patch-style tool, it must provide
"context lines" — surrounding code that identifies the location of the edit.
LLMs frequently hallucinate or slightly misremember these context lines, causing
edits to fail. Common failure modes:

- Leading/trailing whitespace differences (tabs vs. spaces, trailing spaces)
- `\r\n` vs `\n` line ending mismatches
- Minor typos or paraphrasing in context lines
- Hallucinated blank lines at the start/end of the context block
- Indentation drift (e.g., agent copies code from a different indentation level)

## Progressive Matching (implemented)

`_find_context_hits` in `src/tools/_text_editor_utils.py` uses a progressive
strategy, escalating to more permissive matching only when stricter levels fail.
All matching is for position-finding only; the actual splice always uses the
original `lines` array.

### Step 0+1 — Normalized matching (always applied)

EOL is already normalized by `_split_lines_preserve` (splits on `\n`, strips
trailing `\r`). For matching, each line is `.strip()`-ped to remove all
leading/trailing whitespace. This catches:

- Trailing spaces/tabs
- Indentation drift
- `\r` remnants from CRLF files

Very low false-positive risk. Always runs as the first (and often only) attempt.

### Step 3 — Per-line fuzzy matching (fallback)

If normalized matching finds no hit, each candidate position is evaluated using
`difflib.SequenceMatcher` per line. A position is accepted only if **all**
context lines have a similarity ratio >= `1 - FUZZY_MATCH_MAX_ERROR`.

Controlled by: `FUZZY_MATCH_MAX_ERROR = 0.10` in `_text_editor_utils.py`
(default threshold: >= 90% per line).

The "all lines must pass" rule prevents a case where one wildly wrong line is
masked by many correct ones dragging the average up.

### Step 2 — Blank-line edge trimming (not yet implemented)

Idea: strip leading/trailing blank-only context lines from the hunk before
matching, to forgive hallucinated padding blank lines at hunk boundaries.
Not implemented yet because it requires tracking an offset when computing the
actual replacement range.

## Design Decisions

### Per-line vs. whole-block similarity

We use per-line `SequenceMatcher` (list of strings), not whole-block (joined
string). Rationale: per-line with "all must pass" prevents a case where one
completely wrong line is hidden by many correct lines bringing the average up.
Whole-block similarity also has trouble when the block has different line counts.

### Why "all lines must pass" and not average?

Average ratio could mask a completely wrong anchor line. If 9 of 10 lines are
perfect (ratio=1.0) and 1 is completely wrong (ratio=0.0), average is 0.90 —
above threshold — but the match location would be wrong. "All lines" enforces
that every anchor point is plausibly correct before applying.

### Threshold choice

`FUZZY_MATCH_MAX_ERROR = 0.10` (>= 90% per line) is conservative. At this
level, a 20-character line can differ by at most ~2 characters. Raise to 0.15
(85%) for more forgiveness; lower to 0.05 (95%) to reduce false-positive risk
on codebases with lots of structurally similar boilerplate.

### Match method is reported in output

Successful edits report which level matched: "Valid (normalized match)." or
"Valid (fuzzy match)." This helps with debugging agent loops and understanding
when fuzzy matching is firing more than expected.

---

## Research Findings

### How other tools handle context matching

**Aider** uses SEARCH/REPLACE blocks and applies a cascade of matching strategies
in order of decreasing strictness: exact match → missing-indentation correction
(strips/reapplies uniform whitespace offset) → ellipsis placeholder expansion →
`difflib.SequenceMatcher` fuzzy as a last resort. Large hunks are broken into
overlapping sub-hunks; context window size and offset are varied progressively.
The aider docs state that removing these fallbacks "radically increases the number
of hunks which fail to apply." For unified-diff input, a similar multi-pass
relaxation is applied.
Sources: https://aider.chat/docs/more/edit-formats.html, https://aider.chat/docs/unified-diffs.html

**RooCode / Cline** (`apply_diff` tool) uses a "middle-out" strategy: a
`:start_line:` hint anchors the initial candidate region, then the search expands
outward. Similarity is scored via Levenshtein distance on normalized strings.
Configurable confidence threshold ranges 0.8–1.0; 0.85 is cited as a typical
working value. Values below ~0.80 produce too many false-positive matches.
Source: https://docs.roocode.com/advanced-usage/available-tools/apply-diff

**Agentless** (arxiv 2407.01489) sidesteps the problem: it generates patches in
unified-diff format, samples multiple repairs per bug, and selects via regression
test outcomes. Patch-apply correctness is validated by test execution, not text
matching.

**SWE-Edit** (arxiv 2604.26102) trains a subagent (Qwen3-8B via GRPO) to
adaptively choose edit formats, explicitly noting that find-and-replace is
"error-prone."

**Claude Code's `str_replace`** requires exact old-string reproduction. Real-world
GitHub issues document: CRLF vs LF failures (#13456), indentation mismatch between
Read output and file (#10332), and "File has been unexpectedly modified" errors
(#12805). An open feature request (#25775) proposes hash-based line addressing as
an alternative.

### Failure rate data

Can Bölük's "The Harness Problem" (Feb 2026, blog.can.ac) is the most concrete
published evidence: across 16 models, the OpenAI `apply_patch` (diff-blob) format
produced patch failure rates of 50.7% (Grok 4) and 46.2% (GLM-4.7). `str_replace`
was better but still brittle. A hash-based edit tool ("hashline") matched or beat
`str_replace` for every model tested, and gave Grok Code Fast 1 a 6.7% → 68.3%
improvement. This is direct evidence that edit-format mismatch causes large-scale
agent failures that cascade into retry loops.
Source: https://blog.can.ac/2026/02/12/the-harness-problem/

### Per-line vs. whole-block similarity

No paper directly benchmarks this as an isolated variable. In practice, aider
operates at the hunk level (whole block) with sub-hunk fallback for large hunks.
RooCode uses block-level matching with a line anchor. The practitioner consensus
is that block-level matching with a line hint is more robust than pure per-line
diffing, since per-line approaches suffer from repetitive code causing false
positives. Our "all lines must pass" rule is more conservative than aider's
whole-block average but safer for an agent that can retry on failure.

### difflib vs. rapidfuzz

No published paper compares them for this use case. Aider uses
`difflib.SequenceMatcher` (Ratcliff/Obershelp). RapidFuzz is ~40% faster and
handles token-order variation better; `difflib` needs no extra dependency. For
short context blocks (< 20 lines) the speed difference is negligible. The
community treats fuzzy matching as a last resort regardless of library choice —
the fallback strategy design matters more than the library.
Source: https://dev.to/mrquite/smart-text-matching-rapidfuzz-vs-difflib-ge5

### Threshold recommendations

No paper publishes a rigorous ablation. The only practitioner data:
- RooCode documents 0.8–1.0 as the practical range, with 0.85 as a typical default
- Values below 0.80 produce too many false positives in typical source files
- Our default of 0.90 (FUZZY_MATCH_MAX_ERROR=0.10) sits conservatively above this
  floor; raise to 0.85 if agents are still looping on near-misses

### Key takeaway

Progressive / cascading matching is the established pattern (aider, RooCode).
Exact-only tools fail at high rates even with large models. The main design
tension is precision vs. recall: our "all lines >= 90%" rule optimizes for
precision (no silent wrong-location edits) at the cost of recall (will miss
some valid near-misses). For an agent that reports failures and can retry, this
is the right tradeoff.

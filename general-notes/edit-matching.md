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
trailing `\r`). For matching, each line is `.rstrip()`-ped to remove trailing
whitespace only. This catches:

- Trailing spaces/tabs
- `\r` remnants from CRLF files

**Leading whitespace is intentionally NOT stripped.** Stripping leading whitespace
would allow indentation mismatches to pass, but since context lines from the patch
are written into the file as-is, a wrong-indent context line would silently corrupt
the file's indentation. Fixing this properly requires smart reindentation: detect
the indentation delta between the patch's context lines and the matched file lines,
then apply that delta uniformly to all `+` lines in the hunk. Not yet implemented.

Very low false-positive risk. Always runs as the first (and often only) attempt.

### Step 3 — Block fuzzy matching (fallback)

If normalized matching finds no hit, the entire `before` block and each candidate
window are each assembled into a single string (trailing whitespace stripped per
line, `\n` inserted where `has_newline` is True). `difflib.SequenceMatcher` is run
on the two block strings; a position is accepted if the ratio >=
`1 - FUZZY_MATCH_MAX_ERROR`.

Controlled by: `FUZZY_MATCH_MAX_ERROR = 0.05` in `_text_editor_utils.py`
(default threshold: >= 95% for the whole block).

Block-level matching is used rather than per-line so that `\ No newline at end of
file` information (encoded as absent `\n` in the block string) is naturally
incorporated into the similarity score.

### Step 2 — Blank-line edge trimming (not yet implemented)

Idea: strip leading/trailing blank-only context lines from the hunk before
matching, to forgive hallucinated padding blank lines at hunk boundaries.
Not implemented yet because it requires tracking an offset when computing the
actual replacement range.

## Design Decisions

### Per-line vs. whole-block similarity

We use whole-block `SequenceMatcher` (the `before` block and each candidate window
assembled into a single string). This naturally incorporates `\ No newline at end
of file` information (absent `\n` between lines) into the similarity score.
Per-line matching was the previous approach but was replaced because it required
a separate mechanism to handle the no-newline case and was harder to reason about.

### Threshold choice

Leniency is dynamic rather than a fixed constant:

- `MAX_LENIENCY = 0.05` — maximum error fraction allowed (at full leniency, threshold = 95%)
- `MAX_LENIENCY_AT_LINES = 15` — anchor line count at which full leniency applies
- At 1 anchor line: leniency = 0.0, exact match required (fuzzy step skipped entirely)
- Scales linearly between 1 and 15 lines

Rationale: more anchor lines provide more matching evidence, making it safer to
tolerate minor differences without risking a false-positive match at the wrong
location. A single-line context block is inherently ambiguous and must match exactly.

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
- Our max leniency of 0.05 (95% threshold at full leniency) is stricter than
  RooCode's typical value; raise MAX_LENIENCY to 0.10 if agents loop on near-misses

### Key takeaway

Progressive / cascading matching is the established pattern (aider, RooCode).
Exact-only tools fail at high rates even with large models. The main design
tension is precision vs. recall: our "all lines >= 90%" rule optimizes for
precision (no silent wrong-location edits) at the cost of recall (will miss
some valid near-misses). For an agent that reports failures and can retry, this
is the right tradeoff.

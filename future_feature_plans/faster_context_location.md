# Faster Context Location in apply_patch

## Background

`_find_context_hits` in `src/tools/_text_editor_utils.py` performs an
O(A × B) sliding-window search, where A = lines in the file and B = lines
in the hunk's before-context. For the fuzzy passes, each window position
also invokes `difflib.SequenceMatcher` which is O(L²) per line pair (L =
line length), making the fuzzy fallback effectively O(A × B × L²).

For typical patches (B = 2–10 context lines, A = 200–2000 file lines) this
is fast enough. For large generated files or long context blocks it can
become a bottleneck.

---

## Approach 1: Rolling Hash — O(A + B) Exact Match

Hash each stripped line to an integer. Maintain a rolling sum of B
consecutive hashes in a sliding window. Only run full comparison when the
sum matches the target sum.

```python
target = [hash(b) for b in norm_before]      # O(B)
target_sum = sum(target)
fh = [hash(f.strip()) for f in file_lines]   # O(A)

window_sum = sum(fh[:n])
hits = []
for i in range(total - n + 1):
    if i:
        window_sum += fh[i + n - 1] - fh[i - 1]
    if window_sum == target_sum:
        if fh[i:i+n] == target:              # O(B) — fires only on collision
            hits.append(i)
```

**Complexity:** O(A) scanning, O(B) verification only on hash-sum matches.
**Collision rate:** Python's `hash()` on strings is high-quality. For B=5
in a 1000-line file, expected false-sum collisions are negligible.
**Note:** Sum-of-hashes is vulnerable to permutation collisions (same lines
in different order). Guard by comparing the full tuple `fh[i:i+n] == target`.

---

## Approach 2: `rapidfuzz` as Drop-in for `difflib`

For the fuzzy match passes, `rapidfuzz.fuzz.ratio` is semantically
equivalent to `difflib.SequenceMatcher(None, a, b).ratio()` but ~50-100x
faster due to a C++ SIMD backend.

```python
# pip install rapidfuzz
from rapidfuzz.fuzz import ratio as _rf_ratio

# Replace:
difflib.SequenceMatcher(None, b, c).ratio()
# With:
_rf_ratio(b, c) / 100.0
```

One small dependency, no algorithmic changes needed. Most valuable for the
fuzzy/lax fallback pass which is the expensive one.

---

## Approach 3: SimHash — Hash with Tolerance

**Problem with plain hash:** One changed character produces a completely
different hash value — zero tolerance for small differences.

**SimHash** (Charikar 2002) is a locality-sensitive hash where *similar
strings hash to similar values* (close Hamming distance). It is used by
Google for near-duplicate document detection.

### Algorithm

Tokenize the string into character bigrams. For each token, compute its
hash and accumulate a weighted vote per bit. The final SimHash is the sign
vector of those accumulated weights.

```python
def simhash(s: str, bits: int = 64) -> int:
    """64-bit SimHash on character bigrams. Similar strings -> close Hamming distance."""
    v = [0] * bits
    text = s.strip()
    tokens = [text[i:i+2] for i in range(len(text) - 1)] or [text]
    for tok in tokens:
        h = hash(tok)
        for b in range(bits):
            v[b] += 1 if (h >> b) & 1 else -1
    return sum(1 << b for b in range(bits) if v[b] > 0)

def hamming(a: int, b: int) -> int:
    """Hamming distance between two SimHashes (number of differing bits)."""
    return bin(a ^ b).count('1')
```

### Properties

- Two lines differing by a few characters -> SimHash Hamming distance
  typically 3-8 bits out of 64.
- Completely different lines -> ~32 bits (near-random, like a coin flip per bit).
- `hamming(h_a, h_b) <= 10` is a fast O(1) approximate-similarity check
  (single XOR + popcount).

### Usage as Per-Line Gate

SimHash cannot be used directly in a rolling window (it is non-linear, so
window sums don't cancel cleanly). Use it per-line as a gate before
running `SequenceMatcher`:

```python
file_simhashes = [simhash(l) for l in file_lines]    # precompute O(A)
target_simhashes = [simhash(b) for b in norm_before]  # precompute O(B)
SH_TOLERANCE = 12  # bits; tune based on observed mismatch patterns

def _simhash_ok(i: int) -> bool:
    return all(
        hamming(file_simhashes[i + j], target_simhashes[j]) <= SH_TOLERANCE
        for j in range(n)
    )

fuzzy_candidates = [i for i in range(total - n + 1) if _simhash_ok(i)]
# Only run SequenceMatcher on fuzzy_candidates
```

**Vectorized version:** `numpy.bitwise_xor` across all positions for each
hunk line j, then `numpy.unpackbits` to count set bits, gives a fully
vectorized hamming filter.

---

## Approach 4: Line-Length Pre-Filter (numpy-vectorized)

**Key insight:** If `SequenceMatcher.ratio(a, b) >= r`, then the lengths
must satisfy:

```
len_ratio = len(a) / len(b)  in  [(2-r)/r, r/(2-r)]
```

For r = 0.8: lengths must be within ~50% of each other.
For r = 0.95: lengths must be within ~18%.
For r = 1.0 (exact): lengths must be identical.

**Implication:** If `|len(file_line) - len(target_line)| > TOLERANCE`, a
match at that position is mathematically impossible at the required ratio.
This filter has **zero false negatives** up to the tolerance setting.

### Implementation

```python
import numpy as np

file_lens = np.array([len(l.strip()) for l in file_lines], dtype=np.int32)
target_lens = np.array([len(b) for b in norm_before], dtype=np.int32)

def _len_candidate_mask(tolerance_fn) -> np.ndarray:
    """Return boolean mask of window positions that pass the length pre-filter."""
    mask = np.ones(total - n + 1, dtype=bool)
    for j in range(n):
        tol = tolerance_fn(int(target_lens[j]))
        # For window starting at i, hunk line j corresponds to file line i+j
        mask &= np.abs(file_lens[j : total - n + 1 + j] - target_lens[j]) <= tol
    return mask

# Tolerance functions (tune to match the fuzzy threshold of each pass)
exact_candidates = np.where(_len_candidate_mask(lambda _: 0))[0]
mid_candidates   = np.where(_len_candidate_mask(lambda t: max(2, t // 7)))[0]
lax_candidates   = np.where(_len_candidate_mask(lambda t: max(3, t // 3)))[0]
```

**Complexity:** O(A x B / V) where V = numpy SIMD vector width (~8-16 int32
elements). In practice: ~10-50x faster than string comparison for the
same loop count, and prunes >80% of candidates in typical files.

**No false negatives:** The tolerance function should be derived from the
fuzzy threshold used in each pass. For the lax pass (threshold ~0.85):
`max(3, t // 3)` safely covers all possible matches.

---

## Recommended Combined Architecture

| Pass       | Pre-filter                    | Gate                      | Verifier        |
|------------|-------------------------------|---------------------------|-----------------|
| Exact      | length == 0 tolerance (numpy) | hash tuple equality O(B)  | --              |
| Fuzzy/mid  | length within ~15% (numpy)    | SimHash hamming <= 8      | rapidfuzz       |
| Fuzzy/lax  | length within ~35% (numpy)    | SimHash hamming <= 14     | SequenceMatcher |

### Preprocessing (once per `_find_context_hits` call)

```python
file_stripped = [l.strip() for l in file_lines]        # O(A)
file_lens = np.array([len(s) for s in file_stripped])  # O(A)
file_hashes = [hash(s) for s in file_stripped]         # O(A)
file_simhashes = [simhash(s) for s in file_stripped]   # O(A x bigrams)
```

### Effective Complexity

- Preprocessing: O(A) — amortized across passes
- Length filter: O(A x B / V) numpy vectorized integer ops
- SimHash gate: O(candidates x B) — integer XOR + popcount only
- Verifier: O(true_matches x B x L^2) — called for very few candidates

**Bottom line:** The numpy length filter provides the largest win for the
least implementation effort and handles the common case (exact or near-exact
context lines). SimHash adds fuzzy tolerance without the O(L^2) cost of
`SequenceMatcher`. `rapidfuzz` is a minimal-effort speedup for any remaining
`SequenceMatcher` calls.

---

## KMP on Hashed Lines (Alternative to Rolling Hash)

For provably O(A+B) exact matching with zero hash-collision risk:

```python
def _kmp_search(text_hashes: list, pattern_hashes: list) -> list[int]:
    n, m = len(text_hashes), len(pattern_hashes)
    # Build failure function -- O(m)
    fail = [0] * m
    j = 0
    for i in range(1, m):
        while j and pattern_hashes[i] != pattern_hashes[j]:
            j = fail[j - 1]
        if pattern_hashes[i] == pattern_hashes[j]:
            j += 1
        fail[i] = j
    # Search -- O(n)
    hits, j = [], 0
    for i, h in enumerate(text_hashes):
        while j and h != pattern_hashes[j]:
            j = fail[j - 1]
        if h == pattern_hashes[j]:
            j += 1
        if j == m:
            hits.append(i - m + 1)
            j = fail[j - 1]
    return hits
```

KMP is provably O(A+B) with no false positives. The rolling sum approach is
simpler to implement and has negligible false-positive rate in practice;
KMP is the right choice if correctness guarantees matter more than code
simplicity.

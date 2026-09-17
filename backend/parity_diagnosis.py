"""Root-cause triage for a Phase 6 parity mismatch, run BEFORE the repair
agent is invoked for the "parity" stage (orchestrator._verify_chain /
_REPAIR_FNS["parity"] -> llm.repair_parity_mismatch).

Real defect this guards against (2026-09-16, run 01M2PFCANG748NR8D5114YE584,
transaction_posting.cbl): cobol_io_profile.derive_fixture() fills a field like
TR-TYPE with a generic filler value ("COBALTFIXTURE...") that never equals any
of the literals the COBOL PROCEDURE DIVISION actually branches on (e.g.
`IF TR-TYPE = "DEPOSIT"`). The real COBOL oracle then falls through to
whatever ELSE/undefined path handles an unrecognized code — its own output is
not well-defined for that input. Feeding that mismatch straight into
llm.repair_parity_mismatch makes the repair agent "fix" C# code that was never
wrong, burning retry budget and real money on a fixture problem.

diagnose_parity_mismatch() classifies a mismatch BEFORE repair is attempted:
- "fixture_bug": the fixture drove the field into a value with no matching
  literal comparison in the COBOL source, so the oracle's own output cannot
  be trusted as ground truth. Skip C# repair; fix the fixture instead.
- "code_bug": the fixture value matches a real recognized branch (or the
  program has no such literal-driven fields at all), so a real divergence
  between COBOL and C# output is a genuine C# defect. Proceed with repair
  as before.
- "unknown": not enough information to tell (e.g. mismatch_detail doesn't
  carry a parseable COBOL oracle output section).

Standalone by design: cobol_io_profile.derive_fixture() is being fixed in
parallel by another agent in this session. This module does not import or
depend on that fix landing — it only inspects the COBOL source text and the
mismatch detail string already produced by parity_gate.run_parity_gate, so it
composes with whatever fixture behavior is live when orchestrator wires it in
via _REPAIR_FNS["parity"].
"""
from __future__ import annotations

import re
from typing import Literal

Verdict = Literal["code_bug", "fixture_bug", "unknown"]

# Matches `IF TR-TYPE = "DEPOSIT"` / `WHEN TR-TYPE = "WITHDRAWAL"` anywhere in
# the PROCEDURE DIVISION — same shape as cobol_io_profile._literal_comparisons_for_field,
# but scanning the whole source for (field, literal) pairs instead of one
# field at a time, since diagnosis doesn't know in advance which field
# diverged.
_LITERAL_COMPARISON_RE = re.compile(
    r'\b(?:IF|WHEN)\s+([\w-]+)\s*=\s*"([^"]*)"', re.IGNORECASE,
)

# The generic alphanumeric filler cobol_io_profile._alpha_fixture_value()
# tiles into any PIC X field that isn't specifically driven toward a
# recognized literal. Its presence, verbatim, in the COBOL oracle's own
# output is the tell that the fixture — not the C# candidate — produced an
# undefined comparison.
_FIXTURE_FILLER_RE = re.compile(r"COBALTFIXTURE", re.IGNORECASE)

_ORACLE_SECTION_RE = re.compile(
    r"COBOL \(oracle\) output:\n(.*?)\nC# \(candidate\) output:", re.DOTALL,
)


def _extract_oracle_output(mismatch_detail: str) -> str | None:
    m = _ORACLE_SECTION_RE.search(mismatch_detail)
    return m.group(1) if m else None


def _literal_driven_fields(cobol_source: str) -> dict[str, set[str]]:
    """Field name (upper) -> set of literals it is compared against anywhere
    in the source, e.g. {"TR-TYPE": {"DEPOSIT", "WITHDRAWAL"}}."""
    fields: dict[str, set[str]] = {}
    for field_name, literal in _LITERAL_COMPARISON_RE.findall(cobol_source):
        fields.setdefault(field_name.upper(), set()).add(literal)
    return fields


def diagnose_parity_mismatch(
    mismatch_detail: str, cobol_source: str, csharp_source: str,
) -> Verdict:
    """Classifies a parity mismatch as a real C# code bug vs. an invalid
    fixture before the parity repair agent (llm.repair_parity_mismatch) is
    invoked. csharp_source is accepted for symmetry/future use (e.g.
    detecting the candidate independently reproduced the same undefined
    branch) but the current heuristic only needs the COBOL side, since the
    oracle is the one whose behavior is undefined for an unrecognized code.
    """
    literal_fields = _literal_driven_fields(cobol_source)
    if not literal_fields:
        # Program has no literal-comparison branches at all — nothing for a
        # bad fixture value to derail, so a divergence is a real C# bug.
        return "code_bug"

    oracle_output = _extract_oracle_output(mismatch_detail)
    if oracle_output is None:
        return "unknown"

    if _FIXTURE_FILLER_RE.search(oracle_output):
        # The oracle's own output still carries the raw filler tile, meaning
        # the field never matched any of the literals the program branches
        # on — the COBOL run itself took an unrecognized/undefined path.
        return "fixture_bug"

    return "code_bug"

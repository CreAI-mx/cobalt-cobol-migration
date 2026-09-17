from parity_diagnosis import diagnose_parity_mismatch

_COBOL_WITH_TR_TYPE = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TRANSACTION-POSTING.
       PROCEDURE DIVISION.
           IF TR-TYPE = "DEPOSIT"
               PERFORM APPLY-DEPOSIT
           WHEN TR-TYPE = "WITHDRAWAL"
               PERFORM APPLY-WITHDRAWAL
           END-IF.
"""

_COBOL_NO_LITERAL_BRANCHES = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ACCOUNT-LOOKUP.
       PROCEDURE DIVISION.
           ADD 1 TO WS-COUNTER.
           DISPLAY WS-COUNTER.
"""


def test_fixture_bug_when_oracle_output_carries_raw_filler_for_a_literal_driven_field():
    mismatch_detail = (
        "--- TRANSACTION-POSTING MISMATCH ---\n"
        "COBOL (oracle) output:\n"
        "UNRECOGNIZED TRANSACTION CODE: COBALTFIXTURECOBALTFIXTURE\n"
        "C# (candidate) output:\n"
        "Unhandled exception: KeyNotFoundException\n"
    )

    verdict = diagnose_parity_mismatch(
        mismatch_detail, _COBOL_WITH_TR_TYPE, csharp_source="// candidate C#",
    )

    assert verdict == "fixture_bug"


def test_code_bug_when_oracle_output_hit_a_real_recognized_branch():
    mismatch_detail = (
        "--- TRANSACTION-POSTING MISMATCH ---\n"
        "COBOL (oracle) output:\n"
        "DEPOSIT APPLIED. NEW BALANCE: 0000100000\n"
        "C# (candidate) output:\n"
        "DEPOSIT APPLIED. NEW BALANCE: 0000000000\n"
    )

    verdict = diagnose_parity_mismatch(
        mismatch_detail, _COBOL_WITH_TR_TYPE, csharp_source="// candidate C#",
    )

    assert verdict == "code_bug"


def test_code_bug_when_program_has_no_literal_driven_branches_at_all():
    mismatch_detail = (
        "--- ACCOUNT-LOOKUP MISMATCH ---\n"
        "COBOL (oracle) output:\n"
        "1\n"
        "C# (candidate) output:\n"
        "0\n"
    )

    verdict = diagnose_parity_mismatch(
        mismatch_detail, _COBOL_NO_LITERAL_BRANCHES, csharp_source="// candidate C#",
    )

    assert verdict == "code_bug"


def test_unknown_when_mismatch_detail_has_no_parseable_oracle_section():
    verdict = diagnose_parity_mismatch(
        "some free-form log without the expected section markers",
        _COBOL_WITH_TR_TYPE,
        csharp_source="// candidate C#",
    )

    assert verdict == "unknown"

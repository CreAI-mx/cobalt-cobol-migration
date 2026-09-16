"""Regression for the byte-width defect found in the independent architecture
audit of run 01M2K8AVCR27QJFFKS243K1E8K (csharp-reference/): the generated C#
record codec assumed a 10-byte signed numeric (leading sign char) where the
COBOL source declares `PIC S9(7)V99` with no SIGN clause, which is 9 bytes
with the sign overpunched onto the last digit.

Fields below are copied verbatim from the real source, not invented:
migration-state/runs/01M2K8AVCR27QJFFKS243K1E8K/source/cobol-banking-systems/
src/transaction_posting.cbl:16-18 (TRANS-FILE) and :22-23 (ACCT-FILE).
"""
from cobol_layout import compute_pic_width, compute_record_width


def test_display_numeric_width_matches_digit_count():
    assert compute_pic_width("9(10)") == 10


def test_signed_implied_decimal_width_excludes_sign_byte_by_default():
    # PIC S9(7)V99, no SIGN clause in the FD -> overpunched, 9 bytes not 10.
    assert compute_pic_width("S9(7)V99") == 9


def test_signed_implied_decimal_width_adds_byte_only_when_sign_is_separate():
    assert compute_pic_width("S9(7)V99", sign_separate=True) == 10


def test_alphanumeric_width_matches_repeat_count():
    assert compute_pic_width("X(10)") == 10


def test_trans_file_record_width_is_29_not_30():
    # TR-ACCT-NUM PIC 9(10) + TR-AMOUNT PIC S9(7)V99 + TR-TYPE PIC X(10).
    # csharp-reference/CobolRecordCodec.cs:34,39,40 required >=30 and sliced
    # amount at [10,20) — both wrong for this real 29-byte record.
    width = compute_record_width(["9(10)", "S9(7)V99", "X(10)"])
    assert width == 29


def test_acct_file_record_width_is_19_not_20():
    # ACCT-NUM PIC 9(10) + ACCT-BALANCE PIC S9(7)V99.
    # csharp-reference/CobolRecordCodec.cs:11,17,19 required >=20, rejecting
    # this real 19-byte record outright.
    width = compute_record_width(["9(10)", "S9(7)V99"])
    assert width == 19

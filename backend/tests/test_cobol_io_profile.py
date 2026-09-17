"""Regression for the I/O-modality classification used by the Phase 6 parity
gate. Real defect this locks in (2026-09-15): the initial design assumed every
COBOL program reads one value via ACCEPT — true for only 1 of the 3 real
programs in this repo's demo dataset (cobol-banking-systems). Fixtures below
are copied verbatim from the real source, not invented.
"""
from pathlib import Path

from cobol_io_profile import derive_fixture, parse_io_profile

_SRC = Path(
    "/home/frg/creai/cobol/migration-state/runs/01M2KM41FKP2V5Y38628VCWYRC/"
    "source/cobol-banking-systems/src"
)


def test_aml_flagging_is_pure_interactive():
    profile = parse_io_profile((_SRC / "aml_flagging.cbl").read_text())
    assert profile.program_id == "AML-FLAGGING"
    assert profile.mode == "interactive"
    assert profile.files == []
    assert [a.var_name for a in profile.accepts] == ["TR-AMOUNT", "TR-COUNTRY"]


def test_account_lookup_is_interactive_with_lookup_file():
    profile = parse_io_profile((_SRC / "account_lookup.cbl").read_text())
    assert profile.program_id == "ACCOUNT-LOOKUP"
    assert profile.mode == "interactive_with_lookup_file"
    assert len(profile.accepts) == 1
    assert len(profile.files) == 1
    assert profile.files[0].assign_path == "accounts.dat"
    assert profile.files[0].mutated is False


def test_transaction_posting_is_file_batch_with_no_accepts():
    profile = parse_io_profile((_SRC / "transaction_posting.cbl").read_text())
    assert profile.program_id == "TRANSACTION-POSTING"
    assert profile.mode == "file_batch"
    assert profile.accepts == []
    assert len(profile.files) == 2
    mutated = [f for f in profile.files if f.mutated]
    assert len(mutated) == 1
    assert mutated[0].assign_path == "accounts.dat"


def test_derive_fixture_widths_match_real_pic_clauses():
    # accounts.dat record: ACCT-NUM 9(10) + ACCT-NAME X(30) + ACCT-BALANCE
    # S9(7)V99 (9 bytes overpunch) = 49 bytes.
    profile = parse_io_profile((_SRC / "account_lookup.cbl").read_text())
    fixture = derive_fixture(profile)
    assert len(fixture.stdin.rstrip("\n")) == 10
    assert len(fixture.files["accounts.dat"].rstrip("\n")) == 49


def test_transaction_posting_fixtures_share_the_lookup_key():
    # The non-mutated accounts.dat fixture must key-match the mutated
    # transactions.dat fixture so the program's normal (found) path runs,
    # not its "ACCOUNT NOT FOUND" error path.
    profile = parse_io_profile((_SRC / "transaction_posting.cbl").read_text())
    fixture = derive_fixture(profile)
    trans_key = fixture.files["transactions.dat"][:10]
    acct_key = fixture.files["accounts.dat"][:10]
    assert trans_key == acct_key


def test_transaction_posting_detects_tr_type_comparison_literals():
    # Real defect (2026-09-16, run 01M2PFCANG748NR8D5114YE584): TR-TYPE
    # PIC X(10) is compared against "DEPOSIT"/"WITHDRAWAL" literals in the
    # PROCEDURE DIVISION to pick a branch. A generic filler value equal to
    # neither literal leaves the program's AS-IS behavior undefined for
    # that input.
    profile = parse_io_profile((_SRC / "transaction_posting.cbl").read_text())
    assert profile.field_literals.get("TR-TYPE") == "DEPOSIT"


def test_transaction_posting_fixture_uses_real_tr_type_literal_not_generic_fill():
    profile = parse_io_profile((_SRC / "transaction_posting.cbl").read_text())
    fixture = derive_fixture(profile)
    # transactions.dat record: TR-ACCT-NUM 9(10) + TR-AMOUNT S9(7)V99 (9
    # bytes) + TR-TYPE X(10) -> TR-TYPE starts at offset 19.
    tr_type_value = fixture.files["transactions.dat"][19:29]
    assert tr_type_value == "DEPOSIT   "
    assert "COBALTFIXT" not in tr_type_value

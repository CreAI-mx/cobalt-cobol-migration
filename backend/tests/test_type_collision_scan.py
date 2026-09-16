"""Regression test for orchestrator.detect_type_name_collisions().

Real bug this session (run 01M2NN5Q765RDGP4ZCV1Q6WC4H): two work items each
legitimately declared their own `AccountRecord` type in their own
Application.UseCases.* namespace, but the generated Cli/Program.cs referenced
the bare simple name — CS0104 ambiguous reference, plus a CS0738 on any
interface member typed with it. This test reproduces that exact file shape
with zero real dotnet invocation.

Importers: pytest. No real subprocess, no real LLM call, no real dotnet.
"""
from pathlib import Path

import orchestrator


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_detects_ambiguous_same_name_type_across_namespaces(tmp_path):
    csharp = tmp_path / "csharp"

    _write(csharp / "src/Application/UseCases/AccountLookup/AccountRecord.cs", """
namespace CobolBankingSystems.Application.UseCases.AccountLookup;

public sealed record AccountRecord(long AccountNumber, string Name, decimal Balance);
""")

    _write(csharp / "src/Application/UseCases/TransactionPosting/AccountRecord.cs", """
namespace CobolBankingSystems.Application.UseCases.TransactionPosting;

public sealed class AccountRecord
{
    public string AccountNumber { get; set; } = "";
    public string AccountName { get; set; } = "";
    public decimal Balance { get; set; }
}
""")

    _write(csharp / "src/Cli/Program.cs", """
using CobolBankingSystems.Application.UseCases.AccountLookup;
using CobolBankingSystems.Application.UseCases.TransactionPosting;

namespace CobolBankingSystems.Cli;

public class Program
{
    private sealed class FileAccountLookupPort
    {
        public AccountRecord? FindByAccountNumber(long accountNumber) => null;
    }
}
""")

    diagnostic = orchestrator.detect_type_name_collisions(csharp)

    assert diagnostic, "must detect the ambiguous bare 'AccountRecord' reference"
    assert "AccountRecord" in diagnostic
    assert "AccountLookup" in diagnostic
    assert "TransactionPosting" in diagnostic


def test_clean_when_every_reference_is_fully_qualified(tmp_path):
    csharp = tmp_path / "csharp"

    _write(csharp / "src/Application/UseCases/AccountLookup/AccountRecord.cs", """
namespace CobolBankingSystems.Application.UseCases.AccountLookup;

public sealed record AccountRecord(long AccountNumber, string Name, decimal Balance);
""")

    _write(csharp / "src/Application/UseCases/TransactionPosting/AccountRecord.cs", """
namespace CobolBankingSystems.Application.UseCases.TransactionPosting;

public sealed class AccountRecord
{
    public string AccountNumber { get; set; } = "";
}
""")

    _write(csharp / "src/Cli/Program.cs", """
namespace CobolBankingSystems.Cli;

public class Program
{
    private sealed class FileAccountLookupPort
    {
        public CobolBankingSystems.Application.UseCases.AccountLookup.AccountRecord? FindByAccountNumber(long accountNumber) => null;
    }

    private sealed class FileTransactionPostingPort
    {
        public CobolBankingSystems.Application.UseCases.TransactionPosting.AccountRecord? FindAccount(string accountNumber) => null;
    }
}
""")

    assert orchestrator.detect_type_name_collisions(csharp) == ""


def test_ignores_block_comments_and_string_literals(tmp_path):
    """Codex audit finding: original scan only stripped `//` line comments,
    so a bare mention inside `/* */` or a string literal produced a false
    positive that would BLOCK a build that actually compiles fine."""
    csharp = tmp_path / "csharp"

    _write(csharp / "src/Application/UseCases/AccountLookup/AccountRecord.cs", """
namespace CobolBankingSystems.Application.UseCases.AccountLookup;

public sealed record AccountRecord(long AccountNumber, string Name, decimal Balance);
""")

    _write(csharp / "src/Application/UseCases/TransactionPosting/AccountRecord.cs", """
namespace CobolBankingSystems.Application.UseCases.TransactionPosting;

public sealed class AccountRecord
{
    public string AccountNumber { get; set; } = "";
}
""")

    _write(csharp / "src/Cli/Program.cs", """
using CobolBankingSystems.Application.UseCases.AccountLookup;
using CobolBankingSystems.Application.UseCases.TransactionPosting;

namespace CobolBankingSystems.Cli;

/*
 * TransactionRecord/AccountRecord shapes differ between use cases.
 */
public class Program
{
    private const string Note = "AccountRecord layout mirrors account_lookup.cbl";

    private sealed class FileAccountLookupPort
    {
        public CobolBankingSystems.Application.UseCases.AccountLookup.AccountRecord? FindByAccountNumber(long accountNumber) => null;
    }
}
""")

    assert orchestrator.detect_type_name_collisions(csharp) == ""


def test_clean_when_disambiguated_via_namespace_alias(tmp_path):
    """Real false positive found live (run 01M2NN5Q765RDGP4ZCV1Q6WC4H): a
    repair agent correctly disambiguated with `using Alias = Full.Namespace;`
    — valid C#, real dotnet build succeeded with 0 errors — but the scan kept
    blocking it because it didn't recognize `Alias.TypeName` as resolved."""
    csharp = tmp_path / "csharp"

    _write(csharp / "src/Application/UseCases/AccountLookup/AccountRecord.cs", """
namespace CobolBankingSystems.Application.UseCases.AccountLookup;

public sealed record AccountRecord(long AccountNumber, string Name, decimal Balance);
""")

    _write(csharp / "src/Application/UseCases/TransactionPosting/AccountRecord.cs", """
namespace CobolBankingSystems.Application.UseCases.TransactionPosting;

public sealed class AccountRecord
{
    public string AccountNumber { get; set; } = "";
}
""")

    _write(csharp / "src/Infrastructure/Persistence/FileLedgerStore.cs", """
using AccountLookup = CobolBankingSystems.Application.UseCases.AccountLookup;
using TransactionPosting = CobolBankingSystems.Application.UseCases.TransactionPosting;
using CobolBankingSystems.Application.UseCases.AccountLookup;
using CobolBankingSystems.Application.UseCases.TransactionPosting;

namespace CobolBankingSystems.Infrastructure.Persistence;

public sealed class FileLedgerStore
{
    public AccountLookup.AccountRecord? FindByAccountNumber(long accountNumber) => null;

    public TransactionPosting.AccountRecord? FindAccount(string accountNumber) => null;
}
""")

    assert orchestrator.detect_type_name_collisions(csharp) == ""


def test_no_collision_when_names_are_unique(tmp_path):
    csharp = tmp_path / "csharp"

    _write(csharp / "src/Application/UseCases/AccountLookup/AccountRecord.cs", """
namespace CobolBankingSystems.Application.UseCases.AccountLookup;

public sealed record AccountRecord(long AccountNumber, string Name, decimal Balance);
""")

    _write(csharp / "src/Cli/Program.cs", """
using CobolBankingSystems.Application.UseCases.AccountLookup;

namespace CobolBankingSystems.Cli;

public class Program
{
    public AccountRecord? Lookup() => null;
}
""")

    assert orchestrator.detect_type_name_collisions(csharp) == ""

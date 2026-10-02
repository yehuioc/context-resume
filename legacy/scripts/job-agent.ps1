param(
    [Parameter(Position = 0)]
    [string]$Command = "status",

    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$RemainingArgs
)

$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
try {
    $Utf8 = [System.Text.UTF8Encoding]::new($false)
    [Console]::OutputEncoding = $Utf8
    $OutputEncoding = $Utf8
}
catch {
    # Some non-interactive hosts reject console encoding changes; PYTHONUTF8 still applies.
}
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$Python = if (Test-Path -LiteralPath $VenvPython) { $VenvPython } else { "python" }
$Entry = Join-Path $ProjectRoot "src\job_agent.py"

& $Python $Entry $Command @RemainingArgs
exit $LASTEXITCODE

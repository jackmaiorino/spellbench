<#
.SYNOPSIS
Play a human session against a benchmark bot: one command, then open the printed page.

.DESCRIPTION
Runs `python -m spellbench.human` (see python/spellbench/human/session.py) from this checkout. With -SlotTool, the
session runs inside a host_slots_v1.py claim (`run --wait`), so it waits for its cores like any other job.

.EXAMPLE
powershell -ExecutionPolicy Bypass -File python\tools\human_session.ps1 -Python C:\venv\Scripts\python.exe `
  -Local benchmarks\local.json -Out D:\human-sessions -Games 16
#>
param(
    [Parameter(Mandatory = $true)][string]$Python,
    [Parameter(Mandatory = $true)][string]$Local,
    [Parameter(Mandatory = $true)][string]$Out,
    [int]$Games = 16,
    [string]$Decks = "",
    [string]$Opponent = "oh2-r2s1-b512",
    [int]$BankMinutes = 30,
    [string]$Name = "",
    [int]$Port = 8765,
    [string]$Cold = "",
    [switch]$NoRecord,
    [switch]$NoBrowser,
    [string]$SlotTool = "",
    [int]$Cores = 2
)
$ErrorActionPreference = "Stop"
$repoPython = Split-Path -Parent $PSScriptRoot  # the python/ directory: spellbench imports from here
$sessionArgs = @("-u", "-m", "spellbench.human", "--games", $Games, "--opponent", $Opponent, "--local", $Local,
                 "--out", $Out, "--bank-minutes", $BankMinutes, "--port", $Port)
if ($Decks) { $sessionArgs += @("--decks", $Decks) }
if ($Name) { $sessionArgs += @("--name", $Name) }
if ($Cold) { $sessionArgs += @("--cold", $Cold) }
if ($NoRecord) { $sessionArgs += "--no-record" }
if ($NoBrowser) { $sessionArgs += "--no-browser" }
if ($SlotTool) {
    $work = "play-" + (Get-Date -Format "yyyyMMdd-HHmmss")
    Write-Host "Waiting for $Cores cores from the host slot queue..."
    & python -B $SlotTool run --lane human-client --work-id $work --cores $Cores --priority normal --wait `
        --cwd $repoPython -- $Python @sessionArgs
} else {
    Push-Location $repoPython
    try { & $Python @sessionArgs } finally { Pop-Location }
}
exit $LASTEXITCODE

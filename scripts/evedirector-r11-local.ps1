# R11 Windows integration handoff; private EVOE executes only with explicit -AllowLocalEngines.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)]
    [ValidateSet('doctor','stage','verify')]
    [string]$Action,
    [string]$EvoeRoot,
    [string]$OrdrCoreRoot,
    [string]$OrdrAdaptersRoot,
    [string]$InputRoot,
    [string]$OutputRoot,
    [string]$CandidateId,
    [string]$CandidateDir,
    [switch]$AllowLocalEngines
)
$ErrorActionPreference = 'Stop'
$repository = Split-Path -Parent $PSScriptRoot
Push-Location $repository
try {
    $pythonArgs = @('-B','scripts/evedirector_local_handoff_r11.py',$Action)
    if ($EvoeRoot) { $pythonArgs += @('--evoe-root',$EvoeRoot) }
    if ($OrdrCoreRoot) { $pythonArgs += @('--ordr-core-root',$OrdrCoreRoot) }
    if ($OrdrAdaptersRoot) { $pythonArgs += @('--ordr-adapters-root',$OrdrAdaptersRoot) }
    if ($Action -eq 'stage') {
        if (-not $AllowLocalEngines) { throw 'Explicit -AllowLocalEngines required to run private EVOE.' }
        if (-not $EvoeRoot) { throw 'Specify an installed EVOE root.' }
        if (-not $OutputRoot -or -not $CandidateId) { throw 'Stage needs -OutputRoot and -CandidateId.' }
        if ($InputRoot) { $pythonArgs += @('--input-root',$InputRoot) }
        $pythonArgs += @('--output-root',$OutputRoot,'--candidate-id',$CandidateId,'--allow-local-engines')
    } elseif ($Action -eq 'verify') {
        if (-not $CandidateDir) { throw 'Verify requires -CandidateDir.' }
        $pythonArgs += @('--candidate-dir',$CandidateDir)
    }
    & python @pythonArgs
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} finally {
    Pop-Location
}

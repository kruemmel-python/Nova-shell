param(
    [ValidateSet("core", "enterprise")]
    [string]$Profile = "core",
    [switch]$SkipTests,
    [switch]$Clean,
    [string]$OutputDir = "",
    [switch]$Sign,
    [switch]$RefreshBuildEnv,
    [Nullable[Int64]]$SourceDateEpoch = $null,
    [string]$CertificateFile = "",
    [string]$CertificatePassword = "",
    [string]$SubjectName = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$venv = Join-Path $root ".venv-build"
$dotnetTools = Join-Path $HOME ".dotnet\tools"
$stateFile = Join-Path $venv ".nova-shell-build-state.json"
$env:PIP_DISABLE_PIP_VERSION_CHECK = "1"

function Write-Step {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Message
    )

    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Format-Duration {
    param(
        [Parameter(Mandatory = $true)]
        [TimeSpan]$Elapsed
    )

    if ($Elapsed.TotalHours -ge 1) {
        return "{0}h {1}m {2}s" -f [int]$Elapsed.TotalHours, $Elapsed.Minutes, $Elapsed.Seconds
    }
    if ($Elapsed.TotalMinutes -ge 1) {
        return "{0}m {1}s" -f [int]$Elapsed.TotalMinutes, $Elapsed.Seconds
    }
    return "{0}s" -f [int]$Elapsed.TotalSeconds
}

function New-LogReader {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    $directory = Split-Path -Parent $Path
    if ($directory) {
        New-Item -ItemType Directory -Force -Path $directory | Out-Null
    }
    if (-not (Test-Path $Path)) {
        New-Item -ItemType File -Force -Path $Path | Out-Null
    }

    $stream = [System.IO.File]::Open($Path, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
    return [System.IO.StreamReader]::new($stream)
}

function Write-NewLogContent {
    param(
        [Parameter(Mandatory = $true)]
        [System.IO.StreamReader]$Reader,
        [ConsoleColor]$Color = [ConsoleColor]::Gray
    )

    while (($line = $Reader.ReadLine()) -ne $null) {
        Write-Host $line -ForegroundColor $Color
    }
}

function Test-ReleaseBuildCompleted {
    param(
        [Parameter(Mandatory = $true)]
        [string]$StdoutLog,
        [Parameter(Mandatory = $true)]
        [string]$TraceLog
    )

    foreach ($path in @($StdoutLog, $TraceLog)) {
        if (-not (Test-Path $path)) {
            continue
        }
        if (Select-String -Path $path -SimpleMatch "Release build completed" -Quiet) {
            return $true
        }
    }
    return $false
}

function Get-BuildFingerprint {
    $pyproject = Join-Path $root "pyproject.toml"
    return (Get-FileHash $pyproject -Algorithm SHA256).Hash
}

function Get-RequiredBuildModules {
    param(
        [Parameter(Mandatory = $true)]
        [string]$TargetProfile
    )

    $modules = @("build", "nuitka", "psutil", "yaml", "pyarrow", "wasmtime", "numpy", "pyopencl", "platformdirs", "pytools", "typing_extensions", "siphash24", "torch")
    return $modules
}

function Test-BuildDependenciesPresent {
    param(
        [Parameter(Mandatory = $true)]
        [string]$TargetProfile
    )

    $sitePackages = Join-Path $venv "Lib\\site-packages"
    if (-not (Test-Path $sitePackages)) {
        return $false
    }

    foreach ($module in (Get-RequiredBuildModules -TargetProfile $TargetProfile)) {
        $candidates = @(
            Join-Path $sitePackages $module
            Join-Path $sitePackages "$module.py"
            Join-Path $sitePackages "$module.pyd"
            Join-Path $sitePackages "$module.dll"
        )
        $found = $false
        foreach ($candidate in $candidates) {
            if (Test-Path $candidate) {
                $found = $true
                break
            }
        }
        if (-not $found) {
            return $false
        }
    }
    return $true
}

function Test-BuildStateCurrent {
    param(
        [Parameter(Mandatory = $true)]
        [string]$TargetProfile
    )

    if (-not (Test-Path $stateFile)) {
        return $false
    }
    if (-not (Test-BuildDependenciesPresent -TargetProfile $TargetProfile)) {
        return $false
    }

    try {
        $state = Get-Content $stateFile -Raw | ConvertFrom-Json
    } catch {
        return $false
    }

    if ($null -eq $state) {
        return $false
    }

    $fingerprint = Get-BuildFingerprint
    if ($state.fingerprint -ne $fingerprint) {
        return $false
    }

    $stateProfile = [string]$state.profile
    if ($TargetProfile -eq "core") {
        return $stateProfile -in @("core", "enterprise")
    }
    return $stateProfile -eq "enterprise"
}

function Write-BuildState {
    param(
        [Parameter(Mandatory = $true)]
        [string]$TargetProfile
    )

    $state = @{
        profile = $TargetProfile
        fingerprint = Get-BuildFingerprint
    }
    $state | ConvertTo-Json | Set-Content -Path $stateFile -Encoding UTF8
}

function Import-VisualStudioBuildEnvironment {
    $vswhere = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe"
    if (-not (Test-Path $vswhere)) {
        throw "vswhere.exe not found. Install Visual Studio Build Tools 2022 with the C++ workload."
    }

    $installationPath = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
    if (-not $installationPath) {
        throw "No Visual Studio installation with the C++ toolchain was found."
    }

    $devCmd = Join-Path $installationPath "Common7\Tools\VsDevCmd.bat"
    if (-not (Test-Path $devCmd)) {
        throw "VsDevCmd.bat was not found under $installationPath."
    }

    $command = "`"$devCmd`" -no_logo -arch=x64 -host_arch=x64 >nul && set"
    foreach ($line in (& cmd.exe /s /c $command)) {
        if ($line -match '^(.*?)=(.*)$') {
            Set-Item -Path "Env:$($matches[1])" -Value $matches[2]
        }
    }

    $headerFound = $false
    if ($env:INCLUDE) {
        foreach ($path in ($env:INCLUDE -split ';')) {
            if ($path -and (Test-Path (Join-Path $path "excpt.h"))) {
                $headerFound = $true
                break
            }
        }
    }
    if (-not $headerFound) {
        throw "Visual Studio environment was loaded, but 'excpt.h' is still missing from INCLUDE. Repair the C++ workload and Windows SDK installation."
    }
}

if (-not (Test-Path $venv)) {
    Write-Step "Creating build virtual environment at $venv"
    python -m venv $venv
}

$python = Join-Path $venv "Scripts\python.exe"
if ($RefreshBuildEnv) {
    Write-Step "Refreshing build bootstrap tools"
    & $python -m pip install --no-input --upgrade pip
} else {
    Write-Step "Reusing build virtual environment at $venv"
}

$extras = if ($Profile -eq "enterprise") {
    ".[release,observability,guard,arrow,wasm,gpu,atheria]"
} else {
    ".[release,observability,guard,arrow,wasm,gpu,atheria]"
}

Write-Step "Installing build dependencies for profile '$Profile'"
$dependenciesCurrent = $false
if (-not $RefreshBuildEnv) {
    $dependenciesCurrent = Test-BuildStateCurrent -TargetProfile $Profile
}

if ($dependenciesCurrent) {
    Write-Step "Build dependencies already satisfied; skipping pip install"
} else {
    $pipArgs = @("-m", "pip", "install", "--no-input")
    if ($RefreshBuildEnv) {
        $pipArgs += "--upgrade"
    }
    $pipArgs += $extras
    & $python @pipArgs
    Write-BuildState -TargetProfile $Profile
}

if (-not (Get-Command wix -ErrorAction SilentlyContinue)) {
    Write-Step "Installing WiX Toolset"
    dotnet tool install --global wix --version 4.*
}

if (Test-Path $dotnetTools) {
    $env:PATH = "$dotnetTools;$env:PATH"
}

Write-Step "Loading Visual Studio build environment"
Import-VisualStudioBuildEnvironment

$args = @("-u", "scripts/build_release.py", "--profile", $Profile, "--mode", "all")
if ($SkipTests) {
    $args += "--skip-tests"
}
if ($Clean) {
    $args += "--clean"
}
if ($OutputDir) {
    $args += @("--output-dir", $OutputDir)
}
if ($null -ne $SourceDateEpoch) {
    $args += @("--source-date-epoch", $SourceDateEpoch.ToString())
}
if ($Sign) {
    $args += "--windows-sign"
    if ($CertificateFile) {
        $args += @("--windows-cert-file", $CertificateFile)
    }
    if ($CertificatePassword) {
        $args += @("--windows-cert-password", $CertificatePassword)
    }
    if ($SubjectName) {
        $args += @("--windows-subject-name", $SubjectName)
    }
}

Write-Step "Starting release build"
$logDir = Join-Path $root "dist\release\logs"
$logRunId = "{0}-{1}" -f (Get-Date -Format "yyyyMMdd-HHmmss"), $PID
$stdoutLog = Join-Path $logDir "build-windows-$Profile-$logRunId.stdout.log"
$stderrLog = Join-Path $logDir "build-windows-$Profile-$logRunId.stderr.log"
$traceLog = Join-Path $logDir "build-windows-$Profile-$logRunId.trace.log"
$faultLog = Join-Path $logDir "build-windows-$Profile-$logRunId.fault.log"
Write-Step "Streaming release logs from $stdoutLog"

if (Test-Path $stdoutLog) {
    Remove-Item $stdoutLog -Force
}
if (Test-Path $stderrLog) {
    Remove-Item $stderrLog -Force
}
if (Test-Path $traceLog) {
    Remove-Item $traceLog -Force
}
if (Test-Path $faultLog) {
    Remove-Item $faultLog -Force
}

$env:NOVA_BUILD_TRACE_FILE = $traceLog
$env:NOVA_BUILD_FAULT_FILE = $faultLog

$process = Start-Process -FilePath $python `
    -ArgumentList $args `
    -WorkingDirectory $root `
    -NoNewWindow `
    -RedirectStandardOutput $stdoutLog `
    -RedirectStandardError $stderrLog `
    -PassThru

$stdoutReader = New-LogReader -Path $stdoutLog
$stderrReader = New-LogReader -Path $stderrLog
$startedAt = Get-Date
$lastHeartbeat = $startedAt

try {
    while (-not $process.HasExited) {
        Write-NewLogContent -Reader $stdoutReader -Color Gray
        Write-NewLogContent -Reader $stderrReader -Color Yellow

        $now = Get-Date
        if (($now - $lastHeartbeat).TotalSeconds -ge 30) {
            $duration = Format-Duration -Elapsed ($now - $startedAt)
            Write-Step "Release build still running ($duration). Logs: $stdoutLog"
            $lastHeartbeat = $now
        }

        Start-Sleep -Seconds 1
        $process.Refresh()
    }

    Write-NewLogContent -Reader $stdoutReader -Color Gray
    Write-NewLogContent -Reader $stderrReader -Color Yellow
} finally {
    $stdoutReader.Close()
    $stderrReader.Close()
}

$process.WaitForExit()
$process.Refresh()
$exitCode = $process.ExitCode
if ($null -eq $exitCode -and (Test-ReleaseBuildCompleted -StdoutLog $stdoutLog -TraceLog $traceLog)) {
    $exitCode = 0
}
if ($exitCode -ne 0) {
    throw "Release build failed with exit code $exitCode. Review $stdoutLog and $stderrLog."
}

exit 0

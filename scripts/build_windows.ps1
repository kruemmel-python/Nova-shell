param(
    [ValidateSet("core", "enterprise")]
    [string]$Profile = "core",
    [switch]$SkipTests,
    [switch]$Clean,
    [switch]$Sign,
    [Nullable[Int64]]$SourceDateEpoch = $null,
    [string]$CertificateFile = "",
    [string]$CertificatePassword = "",
    [string]$SubjectName = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$venv = Join-Path $root ".venv-build"
$dotnetTools = Join-Path $HOME ".dotnet\tools"

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
    python -m venv $venv
}

$python = Join-Path $venv "Scripts\python.exe"
& $python -m pip install --upgrade pip

$extras = if ($Profile -eq "enterprise") {
    ".[release,observability,guard,arrow,wasm]"
} else {
    ".[release]"
}

& $python -m pip install --upgrade $extras

if (-not (Get-Command wix -ErrorAction SilentlyContinue)) {
    dotnet tool install --global wix --version 4.*
}

if (Test-Path $dotnetTools) {
    $env:PATH = "$dotnetTools;$env:PATH"
}

Import-VisualStudioBuildEnvironment

$args = @("scripts/build_release.py", "--profile", $Profile, "--mode", "all")
if ($SkipTests) {
    $args += "--skip-tests"
}
if ($Clean) {
    $args += "--clean"
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

& $python @args
exit $LASTEXITCODE

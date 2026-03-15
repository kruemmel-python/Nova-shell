[CmdletBinding()]
param(
    [string]$InstallerPath = "",
    [string]$InstallRoot = "$env:ProgramFiles\Nova-shell",
    [string]$BackupRoot = "",
    [string]$LogPath = "",
    [switch]$SkipBackup,
    [switch]$SkipVerify,
    [switch]$DryRun,
    [switch]$Passive
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($LogPath)) {
    $LogPath = Join-Path $env:TEMP ("nova-shell-upgrade-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".log")
}

$script:UpgradeLogPath = $LogPath
$script:MsiLogPath = [System.IO.Path]::ChangeExtension($script:UpgradeLogPath, ".msi.log")

function Write-LogLine {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Message
    )

    $directory = Split-Path -Parent $script:UpgradeLogPath
    if ($directory) {
        New-Item -ItemType Directory -Force -Path $directory | Out-Null
    }
    $timestamp = Get-Date -Format "yyyy-MM-ddTHH:mm:ssK"
    Add-Content -Path $script:UpgradeLogPath -Value "$timestamp $Message"
}

function Write-Step {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Message
    )

    Write-LogLine -Message "STEP $Message"
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Test-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Convert-ToElevationArgumentList {
    param(
        [Parameter(Mandatory = $true)]
        [hashtable]$Parameters
    )

    $arguments = @(
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        $PSCommandPath
    )
    foreach ($entry in $Parameters.GetEnumerator() | Sort-Object Key) {
        if ($entry.Key -in @("DryRun")) {
            continue
        }
        if ($entry.Value -is [switch]) {
            if ($entry.Value.IsPresent) {
                $arguments += "-$($entry.Key)"
            }
            continue
        }
        if ($null -eq $entry.Value) {
            continue
        }
        $text = [string]$entry.Value
        if ([string]::IsNullOrWhiteSpace($text)) {
            continue
        }
        $arguments += "-$($entry.Key)"
        $arguments += $text
    }
    return $arguments
}

function Resolve-DefaultInstallerPath {
    $candidateDirs = [System.Collections.Generic.List[string]]::new()
    if ($PSScriptRoot) {
        $candidateDirs.Add($PSScriptRoot)
        $repoRoot = Split-Path -Parent $PSScriptRoot
        if ($repoRoot) {
            $candidateDirs.Add((Join-Path $repoRoot "dist\release\windows-amd64\core\installers"))
        }
    }

    foreach ($directory in $candidateDirs | Select-Object -Unique) {
        if (-not (Test-Path $directory)) {
            continue
        }
        $candidate = Get-ChildItem -Path $directory -Filter "nova-shell-*-windows-*-core.msi" -File -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTimeUtc -Descending |
            Select-Object -First 1
        if ($candidate) {
            return $candidate.FullName
        }
    }

    throw "Kein Nova-shell-MSI gefunden. Gib -InstallerPath an oder lege das Skript neben den Installer."
}

function Get-PathVariants {
    param(
        [Parameter(Mandatory = $true)]
        [string]$PathValue
    )

    $variants = [System.Collections.Generic.List[string]]::new()
    $fullPath = [System.IO.Path]::GetFullPath($PathValue).TrimEnd("\")
    if ($fullPath) {
        $variants.Add($fullPath)
    }

    try {
        $item = Get-Item -LiteralPath $PathValue -ErrorAction Stop
        $shortCommand = 'for %I in ("' + $item.FullName + '") do @echo %~sI'
        $shortPath = & cmd.exe /d /c $shortCommand
        if ($LASTEXITCODE -eq 0) {
            $shortPath = ([string]$shortPath).Trim()
            if ($shortPath) {
                $variants.Add($shortPath.TrimEnd("\"))
            }
        }
    } catch {
    }

    return $variants | Select-Object -Unique
}

function Stop-InstalledNovaShellProcesses {
    param(
        [Parameter(Mandatory = $true)]
        [string]$TargetRoot,
        [switch]$WhatIfMode
    )

    $rootVariants = Get-PathVariants -PathValue $TargetRoot
    $processes = Get-Process -Name "nova_shell" -ErrorAction SilentlyContinue |
        Where-Object {
            if (-not $_.Path) {
                return $false
            }
            $pathVariants = Get-PathVariants -PathValue $_.Path
            foreach ($rootVariant in $rootVariants) {
                foreach ($pathVariant in $pathVariants) {
                    if ($pathVariant.StartsWith($rootVariant, [System.StringComparison]::OrdinalIgnoreCase)) {
                        return $true
                    }
                }
            }
            return $false
        }

    foreach ($process in $processes) {
        if ($WhatIfMode) {
            Write-Step "Dry-run: wuerde laufenden Prozess stoppen: PID $($process.Id) ($($process.Path))"
            continue
        }
        Write-Step "Stoppe laufenden Prozess: PID $($process.Id) ($($process.Path))"
        Stop-Process -Id $process.Id -Force -ErrorAction Stop
    }
}

function Backup-InstallationRuntime {
    param(
        [Parameter(Mandatory = $true)]
        [string]$TargetRoot,
        [string]$DestinationRoot = "",
        [switch]$WhatIfMode
    )

    if (-not (Test-Path $TargetRoot)) {
        return $null
    }

    $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
    if ([string]::IsNullOrWhiteSpace($DestinationRoot)) {
        $DestinationRoot = Join-Path $env:ProgramData "Nova-shell\upgrade-backups"
    }
    $destination = Join-Path $DestinationRoot $timestamp
    $items = @("Atheria", "nova-shell-runtime.json", "WIKI")

    if ($WhatIfMode) {
        Write-Step "Dry-run: wuerde Runtime-Daten nach $destination sichern"
        return $destination
    }

    New-Item -ItemType Directory -Force -Path $destination | Out-Null
    foreach ($item in $items) {
        $sourcePath = Join-Path $TargetRoot $item
        if (-not (Test-Path $sourcePath)) {
            continue
        }
        $targetPath = Join-Path $destination $item
        Write-Step "Sichere $sourcePath nach $targetPath"
        Copy-Item -Path $sourcePath -Destination $targetPath -Recurse -Force
    }
    return $destination
}

function Invoke-MsiUpgrade {
    param(
        [Parameter(Mandatory = $true)]
        [string]$MsiPath,
        [switch]$PassiveMode,
        [switch]$WhatIfMode
    )

    $arguments = @(
        "/i",
        $MsiPath,
        "REINSTALL=ALL",
        "REINSTALLMODE=amus",
        "MSIFASTINSTALL=7",
        "/norestart",
        "/l*v",
        $script:MsiLogPath
    )
    if ($PassiveMode) {
        $arguments += "/passive"
    } else {
        $arguments += "/qb!"
    }

    if ($WhatIfMode) {
        Write-Step "Dry-run: wuerde Installer starten: msiexec.exe $($arguments -join ' ')"
        return
    }

    Write-Step "Starte MSI-Reinstall"
    Write-LogLine -Message "MSI msiexec.exe $($arguments -join ' ')"
    $process = Start-Process -FilePath "msiexec.exe" -ArgumentList $arguments -PassThru -Wait
    if ($process.ExitCode -ne 0) {
        throw "MSI-Upgrade fehlgeschlagen (ExitCode $($process.ExitCode)). Siehe $script:MsiLogPath"
    }
}

function Invoke-NovaShellCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Executable,
        [Parameter(Mandatory = $true)]
        [string]$Command,
        [string]$ExpectedText = ""
    )

    $output = & $Executable --no-plugins -c $Command 2>&1 | Out-String
    if ($LASTEXITCODE -ne 0) {
        throw "Nova-shell-Kommando fehlgeschlagen: $Command`n$output"
    }
    if ($ExpectedText -and $output -notmatch [Regex]::Escape($ExpectedText)) {
        throw "Nova-shell-Kommando lieferte nicht den erwarteten Text '$ExpectedText': $Command`n$output"
    }
    return $output
}

function Verify-InstalledNovaShell {
    param(
        [Parameter(Mandatory = $true)]
        [string]$TargetRoot,
        [switch]$WhatIfMode
    )

    $executable = Join-Path $TargetRoot "nova_shell.exe"
    if ($WhatIfMode) {
        Write-Step "Dry-run: wuerde Installation pruefen mit doctor, wiki help und wiki build"
        return
    }
    if (-not (Test-Path $executable)) {
        throw "Installierte Nova-shell wurde nicht gefunden: $executable"
    }

    Write-Step "Pruefe installierte Nova-shell"
    Invoke-NovaShellCommand -Executable $executable -Command "doctor" -ExpectedText "Nova-shell" | Out-Null
    Invoke-NovaShellCommand -Executable $executable -Command "wiki help" -ExpectedText "wiki build" | Out-Null

    $wikiSource = Join-Path $TargetRoot "WIKI"
    if (-not (Test-Path $wikiSource)) {
        throw "Die installierte WIKI fehlt unter $wikiSource"
    }

    $wikiOutput = Join-Path $env:TEMP ("nova-shell-wiki-verify-" + [Guid]::NewGuid().ToString("N"))
    try {
        $command = "wiki build --source `"$wikiSource`" --output `"$wikiOutput`""
        Invoke-NovaShellCommand -Executable $executable -Command $command -ExpectedText "home_page" | Out-Null
        $homePage = Join-Path $wikiOutput "Home.html"
        if (-not (Test-Path $homePage)) {
            throw "Die HTML-Wiki wurde nicht korrekt erzeugt: $homePage fehlt."
        }
    } finally {
        Remove-Item -Path $wikiOutput -Recurse -Force -ErrorAction SilentlyContinue
    }
}

if ([string]::IsNullOrWhiteSpace($InstallerPath)) {
    $InstallerPath = Resolve-DefaultInstallerPath
}
$InstallerPath = (Resolve-Path -Path $InstallerPath).ProviderPath
$InstallRoot = [System.IO.Path]::GetFullPath($InstallRoot)

Write-LogLine -Message "InstallerPath=$InstallerPath"
Write-LogLine -Message "InstallRoot=$InstallRoot"
Write-LogLine -Message "UpgradeLog=$script:UpgradeLogPath"
Write-LogLine -Message "MsiLog=$script:MsiLogPath"

if (-not $DryRun -and -not (Test-Administrator)) {
    $elevationParameters = @{}
    foreach ($entry in $PSBoundParameters.GetEnumerator()) {
        $elevationParameters[$entry.Key] = $entry.Value
    }
    $elevationParameters["LogPath"] = $LogPath
    $arguments = Convert-ToElevationArgumentList -Parameters $elevationParameters
    Write-Step "Starte Upgrade mit Administratorrechten neu"
    Write-LogLine -Message "Elevation powershell.exe $($arguments -join ' ')"
    try {
        $process = Start-Process -FilePath "powershell.exe" -Verb RunAs -ArgumentList $arguments -PassThru -Wait
        if ($process.ExitCode -ne 0) {
            throw "Das erhoehte Upgrade ist mit ExitCode $($process.ExitCode) fehlgeschlagen. Siehe $script:UpgradeLogPath"
        }
        return
    } catch {
        throw "Administratorrechte werden benoetigt oder das erhoehte Upgrade ist fehlgeschlagen: $($_.Exception.Message)"
    }
}

try {
    Write-Step "Upgrade-Log: $script:UpgradeLogPath"
    Write-Step "MSI-Log: $script:MsiLogPath"
    Write-Step "Verwende Installer: $InstallerPath"
    Write-Step "Zielverzeichnis: $InstallRoot"

    if (-not $SkipBackup) {
        $backupPath = Backup-InstallationRuntime -TargetRoot $InstallRoot -DestinationRoot $BackupRoot -WhatIfMode:$DryRun
        if ($backupPath) {
            Write-Step "Backup-Ziel: $backupPath"
        }
    }

    Stop-InstalledNovaShellProcesses -TargetRoot $InstallRoot -WhatIfMode:$DryRun
    Invoke-MsiUpgrade -MsiPath $InstallerPath -PassiveMode:$Passive -WhatIfMode:$DryRun

    if (-not $SkipVerify) {
        Verify-InstalledNovaShell -TargetRoot $InstallRoot -WhatIfMode:$DryRun
    }

    Write-Step "Windows-Upgrade abgeschlossen"
} catch {
    Write-LogLine -Message "ERROR $($_.Exception.Message)"
    Write-LogLine -Message "STACK $($_.ScriptStackTrace)"
    throw
}

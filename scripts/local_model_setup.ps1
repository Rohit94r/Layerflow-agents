# LayerFlow Agents - local model host setup for Windows (Ollama + Qwen2.5)
#
# Native Windows port of scripts/local_model_setup.sh. Uses winget + ollama.exe
# and apps\api\.venv\Scripts\python.exe. Works with or without the repo present.
#
#   .\local_model_setup.ps1                      # standard tier (3B + 7B + embed)
#   .\local_model_setup.ps1 -Tier minimal        # 3B + embed only (~2.2 GB)
#   .\local_model_setup.ps1 -Tier stretch        # 14B writer (mostly CPU on 4 GB VRAM)
#   .\local_model_setup.ps1 -WriteEnv            # also update apps\api\.env
#   .\local_model_setup.ps1 -Bench               # run scripts\bench_model.py after
#   .\local_model_setup.ps1 -Check               # report only, change nothing
#   .\local_model_setup.ps1 -RepoPath D:\Layerflow-agents
#
# If PowerShell blocks the file:
#   powershell -ExecutionPolicy Bypass -File .\local_model_setup.ps1 -Check
#
# Re-running is safe (idempotent).

#Requires -Version 5.1
[CmdletBinding()]
param(
    [ValidateSet('minimal', 'standard', 'stretch')]
    [string]$Tier = 'standard',

    [switch]$WriteEnv,
    [switch]$Bench,
    [switch]$Check,
    [switch]$NoInstall,

    [string]$RepoPath = ''
)

$ErrorActionPreference = 'Stop'
$OllamaUrl = 'http://127.0.0.1:11434'

# ---------------------------------------------------------------- output ------
function Write-Step { param([string]$Text) Write-Host ""; Write-Host "==> $Text" -ForegroundColor Cyan }
function Write-Info { param([string]$Text) Write-Host $Text }
function Write-Warn { param([string]$Text) Write-Host "WARN: $Text" -ForegroundColor Yellow }
function Fail      { param([string]$Text) Write-Host ""; Write-Host "ERROR: $Text" -ForegroundColor Red; exit 1 }

# ---------------------------------------------------------------- hardware ----
function Get-Hardware {
    $os = Get-CimInstance Win32_OperatingSystem
    $cs = Get-CimInstance Win32_ComputerSystem

    $ramGb     = [math]::Round($cs.TotalPhysicalMemory / 1GB, 1)
    $freeRamGb = [math]::Round($os.FreePhysicalMemory / 1MB, 1)

    $gpuName = 'unknown'
    $vramGb  = 0
    $driver  = ''

    $smi = Get-Command nvidia-smi -ErrorAction SilentlyContinue
    if ($smi) {
        try {
            $line = (& nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader,nounits 2>$null | Select-Object -First 1)
            if ($line) {
                $parts   = $line -split ',' | ForEach-Object { $_.Trim() }
                $gpuName = $parts[0]
                if ($parts.Count -ge 2 -and $parts[1]) { $vramGb = [math]::Round([double]$parts[1] / 1024, 1) }
                if ($parts.Count -ge 3) { $driver = $parts[2] }
            }
        } catch { }
    }

    if ($vramGb -eq 0) {
        $vc = Get-CimInstance Win32_VideoController -ErrorAction SilentlyContinue |
              Where-Object { $_.Name -notmatch 'Intel|Basic Display|Remote' } |
              Select-Object -First 1
        if ($vc) {
            $gpuName = $vc.Name
            if ($vc.AdapterRAM) { $vramGb = [math]::Round($vc.AdapterRAM / 1GB, 1) }
            if ($vc.DriverVersion) { $driver = $vc.DriverVersion }
        }
    }

    [pscustomobject]@{
        Caption    = $os.Caption
        Build      = $os.BuildNumber
        RamGb      = $ramGb
        FreeRamGb  = $freeRamGb
        GpuName    = $gpuName
        VramGb     = $vramGb
        Driver     = $driver
    }
}

function Find-Repo {
    param([string]$Hint)

    if ($Hint) {
        if (Test-Path (Join-Path $Hint 'apps\api\pyproject.toml')) { return (Resolve-Path $Hint).Path }
        return $null
    }

    $d = $PSScriptRoot
    while ($d) {
        if (Test-Path (Join-Path $d 'apps\api\pyproject.toml')) { return $d }
        $parent = Split-Path $d -Parent
        if (-not $parent -or $parent -eq $d) { break }
        $d = $parent
    }

    foreach ($p in @(
        (Join-Path $env:USERPROFILE 'Layerflow-agents'),
        'D:\Layerflow-agents',
        'D:\projects\Layerflow-agents',
        'C:\projects\Layerflow-agents'
    )) {
        if (Test-Path (Join-Path $p 'apps\api\pyproject.toml')) { return $p }
    }
    return $null
}

function Get-OllamaExe {
    $cmd = Get-Command ollama -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }

    foreach ($c in @(
        (Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'),
        (Join-Path $env:ProgramFiles 'Ollama\ollama.exe')
    )) {
        if (Test-Path $c) { return $c }
    }
    return $null
}

function Test-Ollama {
    try {
        Invoke-RestMethod -Uri "$OllamaUrl/api/tags" -TimeoutSec 3 | Out-Null
        return $true
    } catch { return $false }
}

function Refresh-Path {
    $machine = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $user    = [Environment]::GetEnvironmentVariable('Path', 'User')
    $env:Path = "$machine;$user"
}

function Write-LinesNoBom {
    param([string]$Path, [string[]]$Lines)
    $utf8 = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllLines($Path, [string[]]$Lines, $utf8)
}

function Set-EnvKey {
    param([string]$Path, [string]$Key, [string]$Value)

    $lines = @()
    if (Test-Path $Path) { $lines = @(Get-Content -Path $Path) }

    $found = $false
    $out = foreach ($l in $lines) {
        if ($l -match ('^\s*' + [regex]::Escape($Key) + '\s*=')) {
            $found = $true
            "$Key=$Value"
        } else {
            $l
        }
    }
    if (-not $found) { $out = @($out) + "$Key=$Value" }
    Write-LinesNoBom -Path $Path -Lines @($out)
}

# ---------------------------------------------------------------- tiers -------
$models = switch ($Tier) {
    'minimal'  { @('qwen2.5:3b-instruct', 'nomic-embed-text') }
    'standard' { @('qwen2.5:3b-instruct', 'qwen2.5:7b-instruct', 'nomic-embed-text') }
    'stretch'  { @('qwen2.5:3b-instruct', 'qwen2.5:14b-instruct', 'nomic-embed-text') }
}
$writer = switch ($Tier) {
    'minimal'  { 'qwen2.5:3b-instruct' }
    'standard' { 'qwen2.5:7b-instruct' }
    'stretch'  { 'qwen2.5:14b-instruct' }
}
$needGb = switch ($Tier) { 'minimal' { 2 } 'standard' { 7 } 'stretch' { 10 } }

# ---------------------------------------------------------------- main --------
$hw = Get-Hardware
$RepoRoot = Find-Repo -Hint $RepoPath

$driveLetter = 'C'
if ($RepoRoot) { $driveLetter = (Split-Path -Qualifier $RepoRoot).TrimEnd(':') }
$disk = Get-PSDrive -Name $driveLetter -ErrorAction SilentlyContinue
$freeDiskGb = if ($disk) { [math]::Round($disk.Free / 1GB, 1) } else { 0 }

Write-Step 'LayerFlow local model setup (Windows)'
Write-Info ("OS            : {0} build {1}" -f $hw.Caption, $hw.Build)
Write-Info ("CPU/RAM       : {0} GB total, {1} GB free" -f $hw.RamGb, $hw.FreeRamGb)
Write-Info ("GPU           : {0} ({1} GB VRAM)" -f $hw.GpuName, $hw.VramGb)
Write-Info ("Driver        : {0}" -f $(if ($hw.Driver) { $hw.Driver } else { 'not detected' }))
Write-Info ("Disk {0}: free : {1} GB (need ~{2} GB)" -f $driveLetter, $freeDiskGb, $needGb)
Write-Info ("Tier          : {0} -> {1}" -f $Tier, ($models -join ', '))
Write-Info ("Repo          : {0}" -f $(if ($RepoRoot) { $RepoRoot } else { 'not found (model-host only)' }))
Write-Info ("Endpoint      : {0}" -f $OllamaUrl)

# --- guard rails -------------------------------------------------------------
if ($hw.RamGb -lt 8) {
    Write-Warn "Under 8 GB RAM: use -Tier minimal and expect slow generation."
}
if ($Tier -eq 'standard' -and $hw.RamGb -lt 12) {
    Write-Warn "7B needs ~6-7 GB resident. Close heavy apps or use -Tier minimal."
}
if ($Tier -eq 'stretch' -and $hw.RamGb -lt 16) {
    Fail "14B needs 16 GB+ system RAM. Use -Tier standard on this machine."
}
if ($hw.VramGb -gt 0 -and $hw.VramGb -lt 5 -and $Tier -ne 'minimal') {
    Write-Warn ("Only {0} GB VRAM: the 7B/14B will partly run on CPU. Expect ~8-14 tok/s (7B) / ~4-6 tok/s (14B)." -f $hw.VramGb)
}
if ($Tier -eq 'stretch' -and $hw.VramGb -gt 0 -and $hw.VramGb -lt 8) {
    Write-Warn "14B will be mostly CPU-bound at this VRAM. Fine for batch, painful for live demos."
}
if ($freeDiskGb -gt 0 -and $freeDiskGb -lt ($needGb + 5)) {
    Write-Warn ("Low disk: {0} GB free, want {1} GB. Free space before pulling." -f $freeDiskGb, ($needGb + 5))
}

$driverOk = $true
if ($hw.Driver) {
    try {
        if ([version]$hw.Driver -lt [version]'551.61') { $driverOk = $false }
    } catch { }
}
if (-not $driverOk) {
    Write-Warn ("NVIDIA driver {0} is below Ollama's Windows floor (551.61)." -f $hw.Driver)
    Write-Warn "Ollama will fall back to CPU until you update the NVIDIA driver."
    Write-Warn "Download the current Quadro/RTX driver for the T400 from nvidia.com, then re-run."
}

# --- check-only --------------------------------------------------------------
if ($Check) {
    Write-Step 'Check-only mode'
    $exe = Get-OllamaExe
    if ($exe) {
        Write-Info "Ollama exe    : $exe"
        if (Test-Ollama) {
            Write-Info 'Ollama        : running'
            & $exe list
        } else {
            Write-Info 'Ollama        : installed but not running'
        }
    } else {
        Write-Info 'Ollama        : not installed'
    }
    exit 0
}

# --- install -----------------------------------------------------------------
$exe = Get-OllamaExe
if (-not $exe) {
    if ($NoInstall) { Fail 'Ollama is not installed and -NoInstall was given.' }

    Write-Step 'Installing Ollama'
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($winget) {
        & winget install --id Ollama.Ollama -e --accept-source-agreements --accept-package-agreements --silent
        if ($LASTEXITCODE -ne 0) { Write-Warn "winget returned $LASTEXITCODE; trying the direct installer." }
    }

    $exe = Get-OllamaExe
    if (-not $exe) {
        Write-Info 'Downloading OllamaSetup.exe...'
        $out = Join-Path $env:TEMP 'OllamaSetup.exe'
        Invoke-WebRequest -Uri 'https://ollama.com/download/OllamaSetup.exe' -OutFile $out -UseBasicParsing
        Start-Process -FilePath $out -ArgumentList '/VERYSILENT', '/NORESTART' -Wait
        Refresh-Path
        $exe = Get-OllamaExe
    }

    if (-not $exe) {
        Fail 'Ollama installed but ollama.exe was not found. Open a new PowerShell window and re-run.'
    }
}

# --- keep one model in VRAM at a time (set before the server starts) ----------
[Environment]::SetEnvironmentVariable('OLLAMA_MAX_LOADED_MODELS', '1', 'User')
[Environment]::SetEnvironmentVariable('OLLAMA_KEEP_ALIVE', '15m', 'User')
$env:OLLAMA_MAX_LOADED_MODELS = '1'
$env:OLLAMA_KEEP_ALIVE = '15m'

# --- start -------------------------------------------------------------------
if (-not (Test-Ollama)) {
    Write-Step 'Starting Ollama'
    $appExe = Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama app.exe'
    if (Test-Path $appExe) {
        Start-Process -FilePath $appExe | Out-Null
    } else {
        Start-Process -FilePath $exe -ArgumentList 'serve' -WindowStyle Hidden | Out-Null
    }
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Seconds 1
        if (Test-Ollama) { break }
    }
} else {
    Write-Warn 'Ollama was already running - restart it once so OLLAMA_MAX_LOADED_MODELS=1 takes effect.'
}
if (-not (Test-Ollama)) { Fail "Ollama did not come up at $OllamaUrl. Check the tray app / logs." }
Write-Info "Ollama is up at $OllamaUrl"

# --- pull --------------------------------------------------------------------
foreach ($m in $models) {
    Write-Step "Pulling $m"
    & $exe pull $m
    if ($LASTEXITCODE -ne 0) { Fail "Failed to pull $m (check disk space and network)." }
}

# --- env ---------------------------------------------------------------------
if ($WriteEnv) {
    if (-not $RepoRoot) {
        Write-Warn 'Repo not found, so apps\api\.env was not written. Use -RepoPath <dir>.'
        Write-Info 'Values to add manually:'
        Write-Info "  MODEL_PROVIDER=ollama"
        Write-Info "  OLLAMA_BASE_URL=$OllamaUrl"
        Write-Info "  MODEL_WRITER=$writer"
        Write-Info "  MODEL_FAST=qwen2.5:3b-instruct"
        Write-Info "  MODEL_EMBED=nomic-embed-text"
    } else {
        $envFile = Join-Path $RepoRoot 'apps\api\.env'
        Write-Step "Updating $envFile"
        if (Test-Path $envFile) {
            $stamp = Get-Date -Format 'yyyyMMddHHmmss'
            Copy-Item $envFile "$envFile.bak.$stamp"
            Write-Info 'Backup written next to it'
        } else {
            Write-Warn 'No .env found - creating a minimal one. Copy the rest from SETUP.md section 3.'
            Write-LinesNoBom -Path $envFile -Lines @('APP_ENV=development')
        }
        Set-EnvKey -Path $envFile -Key 'MODEL_PROVIDER'  -Value 'ollama'
        Set-EnvKey -Path $envFile -Key 'OLLAMA_BASE_URL' -Value $OllamaUrl
        Set-EnvKey -Path $envFile -Key 'MODEL_WRITER'    -Value $writer
        Set-EnvKey -Path $envFile -Key 'MODEL_FAST'      -Value 'qwen2.5:3b-instruct'
        Set-EnvKey -Path $envFile -Key 'MODEL_EMBED'     -Value 'nomic-embed-text'
        Set-EnvKey -Path $envFile -Key 'MODEL_TIMEOUT_S' -Value '600'
        Set-EnvKey -Path $envFile -Key 'MODEL_CONCURRENCY' -Value '1'
        Set-EnvKey -Path $envFile -Key 'MODEL_NUM_CTX'   -Value '8192'
        Write-Info "MODEL_WRITER=$writer  MODEL_FAST=qwen2.5:3b-instruct  MODEL_EMBED=nomic-embed-text"
    }
}

# --- verify ------------------------------------------------------------------
Write-Step 'Verify'
& $exe list

# --- bench -------------------------------------------------------------------
if ($Bench) {
    Write-Step "Benchmarking $writer"
    if (-not $RepoRoot) {
        Write-Warn 'Repo not found - cannot run scripts\bench_model.py.'
    } else {
        $py = Join-Path $RepoRoot 'apps\api\.venv\Scripts\python.exe'
        if (Test-Path $py) {
            Push-Location $RepoRoot
            try {
                & $py (Join-Path $RepoRoot 'scripts\bench_model.py') --model $writer --runs 3
            } finally {
                Pop-Location
            }
        } else {
            Write-Warn 'apps\api\.venv missing - skipping bench. Create it first:'
            Write-Info '  cd apps\api'
            Write-Info '  py -3.12 -m venv .venv'
            Write-Info '  .\.venv\Scripts\Activate.ps1'
            Write-Info '  pip install -e ".[dev]"'
        }
    }
}

# --- summary -----------------------------------------------------------------
Write-Step 'Done'
@"
Next steps:
  1. Ensure apps\api\.env has MODEL_PROVIDER=ollama (use -WriteEnv to set it).
  2. Start the API + worker + web per SETUP.md sections 5-6 (three terminals).
     scripts\dev.sh is bash-only; use Git Bash or WSL if you want the one-command launcher.
  3. Dashboard -> Settings -> Models -> Test (expect latency + sample reply).
  4. Measure this machine:       cd apps\api
                                 .\.venv\Scripts\python.exe ..\..\scripts\bench_model.py --model $writer

Notes:
  * One model in VRAM at a time: OLLAMA_MAX_LOADED_MODELS=1 (set for your user).
  * Swap writer to the 3B for snappy demos: MODEL_WRITER=qwen2.5:3b-instruct
  * NVIDIA driver must be 551.61+ for GPU acceleration; 472.47 runs CPU-only.
  * The Intel UHD 770 is ignored by Ollama - only the T400 counts.
"@

<#
.SYNOPSIS
    NIDS Demo Launcher — starts all components for the live demonstration.

.DESCRIPTION
    Starts the full NIDS stack in separate terminal windows:
      1. Docker infra  (Redis, Kafka, Cassandra)
      2. Local Dashboard
      3. Spark ML Pipeline
      4. Kafka Producer  (streams CSV data)
      5. EC2 Sync        (pushes alerts to EC2 every 60s)

    Press ENTER at the end to stop everything cleanly.

.EXAMPLE
    .\demo_start.ps1
#>

# ─── Helpers ──────────────────────────────────────────────────────────────────

function Write-Color([string]$Text, [string]$Color = "White") {
    Write-Host $Text -ForegroundColor $Color
}

function Write-Banner {
    Clear-Host
    Write-Color ""
    Write-Color "  ███╗   ██╗██╗██████╗ ███████╗    ██████╗ ███████╗███╗   ███╗ ██████╗ " "Cyan"
    Write-Color "  ████╗  ██║██║██╔══██╗██╔════╝    ██╔══██╗██╔════╝████╗ ████║██╔═══██╗" "Cyan"
    Write-Color "  ██╔██╗ ██║██║██║  ██║███████╗    ██║  ██║█████╗  ██╔████╔██║██║   ██║" "Cyan"
    Write-Color "  ██║╚██╗██║██║██║  ██║╚════██║    ██║  ██║██╔══╝  ██║╚██╔╝██║██║   ██║" "Cyan"
    Write-Color "  ██║ ╚████║██║██████╔╝███████║    ██████╔╝███████╗██║ ╚═╝ ██║╚██████╔╝" "Cyan"
    Write-Color "  ╚═╝  ╚═══╝╚═╝╚═════╝ ╚══════╝    ╚═════╝ ╚══════╝╚═╝     ╚═╝ ╚═════╝ " "Cyan"
    Write-Color ""
    Write-Color "  Network Intrusion Detection System — Live Demo Launcher" "Yellow"
    Write-Color "  ─────────────────────────────────────────────────────────" "DarkGray"
    Write-Color ""
}

function Write-Step([int]$Num, [string]$Title, [string]$Status = "START") {
    $color = switch ($Status) {
        "START"   { "Yellow" }
        "OK"      { "Green" }
        "SKIP"    { "DarkGray" }
        "ERROR"   { "Red" }
        default   { "White" }
    }
    Write-Color "  [$Status] Step $Num — $Title" $color
}

function Wait-DockerHealthy([string]$ContainerName, [int]$MaxWait = 60) {
    Write-Color "         Waiting for $ContainerName to be healthy..." "DarkGray"
    $elapsed = 0
    while ($elapsed -lt $MaxWait) {
        $status = docker inspect --format "{{.State.Health.Status}}" $ContainerName 2>$null
        if ($status -eq "healthy") { return $true }
        Start-Sleep 3
        $elapsed += 3
        Write-Host "." -NoNewline -ForegroundColor DarkGray
    }
    Write-Host ""
    return $false
}

function Open-DemoWindow([string]$Title, [string]$Commands) {
    # Opens a new PowerShell window with a coloured title bar.
    $script = @"
`$host.UI.RawUI.WindowTitle = '$Title'
Set-Location '$PWD'
`$env:PYTHONPATH = '.;src'
$Commands
Write-Host ''
Write-Host 'Process ended. Window will stay open.' -ForegroundColor Yellow
Read-Host 'Press ENTER to close'
"@
    $tmpFile = [System.IO.Path]::GetTempFileName() + ".ps1"
    $script | Set-Content -Path $tmpFile -Encoding UTF8
    $proc = Start-Process powershell.exe `
        -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$tmpFile`"" `
        -PassThru
    return $proc
}

# ─── Script Root ──────────────────────────────────────────────────────────────
$ProjectRoot = $PSScriptRoot
if (-not $ProjectRoot) { $ProjectRoot = Get-Location }
Set-Location $ProjectRoot

# ─── Banner ───────────────────────────────────────────────────────────────────
Write-Banner

# ─── Step 0: Collect Inputs ───────────────────────────────────────────────────
Write-Color "  SETUP" "Magenta"
Write-Color "  ─────────────────────────────────────────────────────────" "DarkGray"
Write-Color ""

# EC2 IP
do {
    $EC2_IP = Read-Host "  Enter EC2 public IP address (e.g. 52.66.10.5)"
    $EC2_IP = $EC2_IP.Trim()
    if ($EC2_IP -eq "") {
        Write-Color "  EC2 IP is required." "Red"
    }
} while ($EC2_IP -eq "")

$EC2_URL = "http://$EC2_IP"

Write-Color ""

# Data source
$DefaultData = "data\UNSW-NB15\sample.csv"
$DataInput = Read-Host "  Data file path (press ENTER for default: $DefaultData)"
$DataInput = $DataInput.Trim()

if ($DataInput -eq "") {
    $DataFile = $DefaultData
} elseif (Test-Path $DataInput) {
    $DataFile = $DataInput
    Write-Color "  Using custom data: $DataFile" "Green"
} else {
    Write-Color "  Path not found: '$DataInput' — falling back to default." "Yellow"
    $DataFile = $DefaultData
}

if (-not (Test-Path $DataFile)) {
    Write-Color ""
    Write-Color "  ERROR: Data file not found: $DataFile" "Red"
    Write-Color "  Make sure the file exists and re-run this script." "Red"
    Read-Host "  Press ENTER to exit"
    exit 1
}

Write-Color ""
Write-Color "  ─────────────────────────────────────────────────────────" "DarkGray"
Write-Color "  EC2 URL    : $EC2_URL" "Cyan"
Write-Color "  Data file  : $DataFile" "Cyan"
Write-Color "  Ingest key : devops-demo" "Cyan"
Write-Color "  ─────────────────────────────────────────────────────────" "DarkGray"
Write-Color ""

$confirm = Read-Host "  Ready to launch? (Y/n)"
if ($confirm -match "^[Nn]") {
    Write-Color "  Aborted." "Yellow"
    exit 0
}

Write-Color ""

# ─── Collect PIDs for cleanup ─────────────────────────────────────────────────
$Procs = @()

# ─── Step 1: Docker infra ─────────────────────────────────────────────────────
Write-Step 1 "Starting Docker infra (Redis, Kafka, Cassandra)"
docker compose -f docker-compose.local.yml --profile full up -d 2>&1 | Out-Null

# Wait for Redis to be healthy (Kafka + Cassandra may take longer but that's OK)
$redisOK = Wait-DockerHealthy "nids_redis" 60
Write-Host ""
if ($redisOK) {
    Write-Step 1 "Docker infra running (Redis healthy)" "OK"
} else {
    Write-Step 1 "Docker infra may not be fully ready — continuing anyway" "SKIP"
}

Start-Sleep 5  # Give Kafka a moment to stabilise

# ─── Step 2: Local Dashboard ──────────────────────────────────────────────────
Write-Step 2 "Launching Local Dashboard"
$dashCmd = @"
`$env:REDIS_HOST = 'localhost'
`$env:REDIS_PORT = '6379'
`$env:NIDS_DISABLE_CASSANDRA = '1'
Write-Host '[Dashboard] Starting on http://localhost:5000' -ForegroundColor Green
.\\venv\\Scripts\\python.exe -m dashboard.app
"@
$p2 = Open-DemoWindow "NIDS — Local Dashboard" $dashCmd
$Procs += $p2
Start-Sleep 3
Write-Step 2 "Local Dashboard → http://localhost:5000" "OK"

# ─── Step 3: Spark ML Pipeline ────────────────────────────────────────────────
Write-Step 3 "Launching Spark ML Pipeline (GBT + RF inference)"
$pipelineCmd = @"
`$env:JAVA_HOME              = '$ProjectRoot\tools\jdk-17.0.12'
`$env:REDIS_HOST             = 'localhost'
`$env:REDIS_PORT             = '6379'
`$env:KAFKA_BOOTSTRAP_SERVERS = 'localhost:19092'
`$env:NIDS_DISABLE_CASSANDRA = '1'
Write-Host '[Pipeline] Loading models and waiting for Kafka messages...' -ForegroundColor Green
.\\venv\\Scripts\\python.exe -m streaming.pipeline_runner
"@
$p3 = Open-DemoWindow "NIDS — Spark ML Pipeline" $pipelineCmd
$Procs += $p3
Write-Step 3 "Spark ML Pipeline started (loading models...)" "OK"
Start-Sleep 5

# ─── Step 4: Kafka Producer ───────────────────────────────────────────────────
Write-Step 4 "Launching Kafka Producer → streaming $DataFile"
$producerCmd = @"
`$env:KAFKA_BOOTSTRAP_SERVERS = 'localhost:19092'
Write-Host '[Producer] Streaming data from $DataFile at 10 rows/sec...' -ForegroundColor Green
.\\venv\\Scripts\\python.exe kafka_producer.py ``
    --file '$DataFile' ``
    --rate 10 ``
    --loop
"@
$p4 = Open-DemoWindow "NIDS — Kafka Producer" $producerCmd
$Procs += $p4
Write-Step 4 "Kafka Producer streaming → topic: network-traffic" "OK"

# ─── Step 5: EC2 Sync ────────────────────────────────────────────────────────
Write-Step 5 "Launching EC2 Sync → pushing alerts to $EC2_URL"
$syncCmd = @"
`$env:EC2_URL      = '$EC2_URL'
`$env:INGEST_TOKEN = 'devops-demo'
`$env:SYNC_SESSION_ID = 'demo-session'
Write-Host '[Sync] Pushing local alerts to EC2 every 60s...' -ForegroundColor Green
.\\venv\\Scripts\\python.exe sync_push.py --loop --interval 60
"@
$p5 = Open-DemoWindow "NIDS — EC2 Sync" $syncCmd
$Procs += $p5
Write-Step 5 "EC2 Sync → $EC2_URL/api/ingest (every 60s)" "OK"

# ─── Status Board ─────────────────────────────────────────────────────────────
Write-Color ""
Write-Color "  ─────────────────────────────────────────────────────────" "DarkGray"
Write-Color "  ALL COMPONENTS RUNNING" "Green"
Write-Color "  ─────────────────────────────────────────────────────────" "DarkGray"
Write-Color ""
Write-Color "  Local Dashboard  →  http://localhost:5000" "Cyan"
Write-Color "  EC2 Dashboard    →  $EC2_URL" "Cyan"
Write-Color "  EC2 Health       →  $EC2_URL/api/health" "Cyan"
Write-Color ""
Write-Color "  DEMO FLOW:" "Yellow"
Write-Color "    sample.csv → Kafka → Spark (GBT+RF) → Redis (local)" "White"
Write-Color "    Redis (local) → sync_push.py → EC2 Redis → EC2 Dashboard" "White"
Write-Color ""
Write-Color "  JENKINS CI/CD:" "Yellow"
Write-Color "    Make a code change → git push → Jenkins auto-deploys to EC2" "White"
Write-Color "    Jenkins URL  →  http://localhost:8080" "Cyan"
Write-Color ""
Write-Color "  ─────────────────────────────────────────────────────────" "DarkGray"
Write-Color ""

# Wait
Write-Color "  Press ENTER to STOP everything and shut down all services..." "Yellow"
Read-Host "" | Out-Null

# ─── Teardown ─────────────────────────────────────────────────────────────────
Write-Color ""
Write-Color "  Stopping all components..." "Yellow"
Write-Color ""

# Kill spawned windows
foreach ($p in $Procs) {
    try {
        if (-not $p.HasExited) {
            # Kill the child powershell process tree
            Get-Process -Id $p.Id -ErrorAction SilentlyContinue |
                ForEach-Object { Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue }
            Write-Color "  Stopped PID $($p.Id)" "DarkGray"
        }
    } catch { }
}

# Kill any stray python processes that were spawned from those windows
Write-Color "  Stopping Python processes..." "DarkGray"
Get-Process python* -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -like "*$ProjectRoot*" } |
    ForEach-Object { Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue }

# Stop Docker services
Write-Color "  Stopping Docker services..." "DarkGray"
docker compose -f docker-compose.local.yml --profile full down 2>&1 | Out-Null
docker compose -f docker-compose.deploy.yml down 2>&1 | Out-Null  # local deploy stack if running

Write-Color ""
Write-Color "  ─────────────────────────────────────────────────────────" "DarkGray"
Write-Color "  All services stopped. Demo complete!" "Green"
Write-Color "  ─────────────────────────────────────────────────────────" "DarkGray"
Write-Color ""

Read-Host "  Press ENTER to close this window"

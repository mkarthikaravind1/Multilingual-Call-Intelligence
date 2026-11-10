# PowerShell Startup Script for Call Analysis LLM Server (GPU / Windows)
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location (Join-Path $ScriptDir "..")

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "Starting Call Analysis LLM Server (GPU / Windows Stack)" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

if (-not (Test-Path ".env")) {
    Write-Host "[!] .env not found. Copying .env.example to .env..." -ForegroundColor Yellow
    Copy-Item ".env.example" ".env"
}

# Parse .env file
Get-Content ".env" | ForEach-Object {
    $line = $_.Trim()
    if ($line -and -not $line.StartsWith("#")) {
        $parts = $line.Split("=", 2)
        if ($parts.Length -eq 2) {
            [System.Environment]::SetEnvironmentVariable($parts[0].Trim(), $parts[1].Trim(), "Process")
        }
    }
}

$ProxyPort = if ($env:PROXY_PORT) { $env:PROXY_PORT } else { "8091" }
$ModelPath = if ($env:MODEL_PATH) { $env:MODEL_PATH } else { "openai/gpt-oss-20b" }

Write-Host "[+] Target Model: $ModelPath" -ForegroundColor Green
Write-Host "[+] External Gateway Port: $ProxyPort" -ForegroundColor Green

if (Get-Command docker -ErrorAction SilentlyContinue) {
    Write-Host "[+] Launching via Docker Compose with NVIDIA GPU..." -ForegroundColor Green
    docker compose --profile gpu up -d --build
    Write-Host "[+] Check health: curl http://localhost:$ProxyPort/health" -ForegroundColor Yellow
} else {
    Write-Host "[!] Docker not detected. Starting Gateway with Mock Fallback for local testing..." -ForegroundColor Yellow
    $env:ALLOW_MOCK_FALLBACK = "true"
    python proxy/main.py
}

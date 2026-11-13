# PowerShell Startup Script for Call Analysis LLM Server (CPU / Windows)
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location (Join-Path $ScriptDir "..")

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "Starting Call Analysis LLM Server (CPU / llama.cpp)" -ForegroundColor Cyan
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

if (Get-Command docker -ErrorAction SilentlyContinue) {
    Write-Host "[+] Launching CPU container via Docker Compose..." -ForegroundColor Green
    docker compose --profile cpu up -d --build
} else {
    Write-Host "[+] Starting Gateway Proxy with Mock Engine fallback on port $ProxyPort..." -ForegroundColor Green
    $env:ALLOW_MOCK_FALLBACK = "true"
    python proxy/main.py
}

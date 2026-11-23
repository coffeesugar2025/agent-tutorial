# =============================================================================
# 星图商城 · 一键启动（Windows / PowerShell 5.1+）
#
#   .\scripts\up.ps1               全栈启动
#   .\scripts\up.ps1 -Build        全栈启动并重建镜像（首次）
#   .\scripts\up.ps1 -Infra        只启中间件
# =============================================================================
[CmdletBinding()]
param(
    [switch]$Infra,
    [switch]$Build,
    [switch]$Help
)

$ErrorActionPreference = 'Stop'

function Show-Usage {
    @(
        '用法: .\scripts\up.ps1 [-Infra] [-Build] [-Help]',
        '',
        '  -Infra   只启动中间件（mysql redis rabbitmq etcd minio milvus）',
        '  -Build   启动前重建镜像（代码变更 / 首次启动时使用）',
        '  -Help    显示本帮助',
        '',
        '常用:',
        '  .\scripts\up.ps1 -Build    # 全栈首次启动',
        '  .\scripts\up.ps1 -Infra    # 本地用 uv / mvn 跑后端'
    ) | ForEach-Object { Write-Host $_ }
}

if ($Help) { Show-Usage; exit 0 }

$DeployDir = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $DeployDir

$ComposeFile = if ($Infra) { 'docker-compose.infra.yml' } else { 'docker-compose.yml' }

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host '[ERROR] 未找到 docker，请先安装 Docker Desktop' -ForegroundColor Red
    exit 1
}

# 优先 compose 插件，回退独立二进制
$ComposeExe = 'docker'
$ComposePrefix = @('compose')
docker compose version *> $null
if ($LASTEXITCODE -ne 0) {
    if (Get-Command docker-compose -ErrorAction SilentlyContinue) {
        Write-Host '[WARN] 未检测到 docker compose 插件，回退到 docker-compose' -ForegroundColor Yellow
        $ComposeExe = 'docker-compose'
        $ComposePrefix = @()
    }
    else {
        Write-Host '[ERROR] 需要 Docker Compose（docker compose 或 docker-compose）' -ForegroundColor Red
        exit 1
    }
}

function Invoke-Compose {
    param([string[]]$Arguments)
    $all = @()
    $all += $ComposePrefix
    $all += $Arguments
    & $ComposeExe @all
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

if (-not (Test-Path -LiteralPath '.env')) {
    Write-Host '[INFO] 未发现 .env，已从 .env.example 生成（默认 MOCK_LLM=true，可离线体验）'
    Copy-Item -LiteralPath '.env.example' -Destination '.env'
}

Write-Host "[INFO] 编排文件: $ComposeFile"

$upArgs = @('-f', $ComposeFile, 'up', '-d')
if ($Build) { $upArgs += '--build' }
Invoke-Compose -Arguments $upArgs

Invoke-Compose -Arguments @('-f', $ComposeFile, 'ps')

function Get-EnvValue {
    param([string]$Key, [string]$Default)
    if (-not (Test-Path -LiteralPath '.env')) { return $Default }
    $pattern = '^' + [regex]::Escape($Key) + '='
    $line = Get-Content -LiteralPath '.env' |
        Where-Object { $_ -match $pattern } |
        Select-Object -Last 1
    if (-not $line) { return $Default }
    return $line.Substring($line.IndexOf('=') + 1)
}

$FrontendPort     = Get-EnvValue 'FRONTEND_PORT' '8088'
$PythonPort       = Get-EnvValue 'APP_PORT_PYTHON' '8000'
$JavaPort         = Get-EnvValue 'APP_PORT_JAVA' '8080'
$MinioConsolePort = Get-EnvValue 'MINIO_CONSOLE_PORT' '9001'
$RabbitMgmtPort   = Get-EnvValue 'RABBITMQ_MGMT_PORT' '15672'

Write-Host ''
Write-Host '==================== 启动完成 ====================' -ForegroundColor Green
Write-Host "前端             http://localhost:$FrontendPort"
Write-Host "Python 后端      http://localhost:$PythonPort/health"
Write-Host "Java 后端        http://localhost:$JavaPort/health"
Write-Host "RabbitMQ 控制台  http://localhost:$RabbitMgmtPort  (ecom / ecom123)"
Write-Host "MinIO 控制台     http://localhost:$MinioConsolePort  (minioadmin / minioadmin123)"
Write-Host ''
Write-Host '首次启动 Milvus 约需 60-120s，期间后端会因依赖未就绪自动重试。'
Write-Host '查看日志: docker compose -f deploy\docker-compose.yml logs -f --tail 100'
Write-Host '重置数据: .\scripts\down.ps1 -Volumes'
Write-Host '=================================================' -ForegroundColor Green

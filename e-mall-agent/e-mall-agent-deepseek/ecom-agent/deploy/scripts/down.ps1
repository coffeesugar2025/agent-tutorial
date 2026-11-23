# =============================================================================
# 星图商城 · 停止服务（Windows / PowerShell 5.1+）
#
#   .\scripts\down.ps1             停止并删容器，保留数据卷
#   .\scripts\down.ps1 -Volumes    同时删除数据卷（数据全清）
#   .\scripts\down.ps1 -Purge      删容器 + 删卷 + 删本项目镜像
#   .\scripts\down.ps1 -Infra      只处理中间件
# =============================================================================
[CmdletBinding()]
param(
    [switch]$Infra,
    [switch]$Volumes,
    [switch]$Purge,
    [switch]$Help
)

$ErrorActionPreference = 'Stop'

function Show-Usage {
    @(
        '用法: .\scripts\down.ps1 [-Infra] [-Volumes] [-Purge] [-Help]',
        '',
        '  -Infra    只处理中间件编排文件',
        '  -Volumes  删除数据卷（不可恢复，慎用）',
        '  -Purge    删除数据卷 + 本项目镜像'
    ) | ForEach-Object { Write-Host $_ }
}

if ($Help) { Show-Usage; exit 0 }

$DeployDir = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $DeployDir

$ComposeFile = if ($Infra) { 'docker-compose.infra.yml' } else { 'docker-compose.yml' }

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host '[ERROR] 未找到 docker' -ForegroundColor Red
    exit 1
}

$ComposeExe = 'docker'
$ComposePrefix = @('compose')
docker compose version *> $null
if ($LASTEXITCODE -ne 0) {
    if (Get-Command docker-compose -ErrorAction SilentlyContinue) {
        $ComposeExe = 'docker-compose'
        $ComposePrefix = @()
    }
    else {
        Write-Host '[ERROR] 需要 Docker Compose（docker compose 或 docker-compose）' -ForegroundColor Red
        exit 1
    }
}

$downArgs = @('-f', $ComposeFile, 'down')
if ($Volumes -or $Purge) { $downArgs += '-v' }

Write-Host "[INFO] 编排文件: $ComposeFile"
if ($Volumes -or $Purge) {
    Write-Host '[WARN] 将删除数据卷（mysql/redis/rabbitmq/etcd/minio/milvus 全部数据）' -ForegroundColor Yellow
}

$all = @()
$all += $ComposePrefix
$all += $downArgs
& $ComposeExe @all
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if ($Purge) {
    Write-Host '[INFO] 删除本项目镜像前缀 xingtu/ecom-*'
    $images = docker images --format '{{.Repository}}:{{.Tag}}' |
        Where-Object { $_ -like 'xingtu/ecom-*' }
    foreach ($img in $images) {
        docker rmi -f $img *> $null
    }
}

Write-Host '[OK] 已停止' -ForegroundColor Green

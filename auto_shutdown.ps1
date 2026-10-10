# 监控抽帧任务完成后自动关机
# 用法: 在PowerShell中运行 .\auto_shutdown.ps1

Write-Host "=== 自动关机监控已启动 ===" -ForegroundColor Green
Write-Host "监控目标: batch_add_d_material.py (抽帧任务)"
Write-Host "任务完成后将在60秒后自动关机，可运行 shutdown /a 取消"
Write-Host ""

$target = "batch_add_d_material.py"
$checkInterval = 30  # 每30秒检查一次
$shutdownDelay = 60  # 关机前等待60秒

while ($true) {
    $procs = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue
    $found = $false
    foreach ($p in $procs) {
        if ($p.CommandLine -like "*$target*") {
            $found = $true
            $cpu = [math]::Round($p.UserModeTime/10000000, 1)
            Write-Host "[$(Get-Date -Format 'HH:mm:ss')] 抽帧任务运行中 (PID:$($p.ProcessId), CPU:${cpu}s)"
            break
        }
    }

    if (-not $found) {
        Write-Host "[$(Get-Date -Format 'HH:mm:ss')] 抽帧任务已结束！" -ForegroundColor Yellow
        Write-Host "等待30秒确认..."
        Start-Sleep -Seconds 30

        # 再次确认
        $procs2 = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue
        $stillRunning = $false
        foreach ($p in $procs2) {
            if ($p.CommandLine -like "*$target*") {
                $stillRunning = $true
                break
            }
        }

        if (-not $stillRunning) {
            Write-Host "确认任务已完成，将在 $shutdownDelay 秒后关机..." -ForegroundColor Red
            Write-Host "取消关机请运行: shutdown /a" -ForegroundColor Yellow
            shutdown /s /t $shutdownDelay /c "视频处理任务已完成，将在60秒后自动关机。取消请运行 shutdown /a"
            break
        } else {
            Write-Host "任务仍在运行，继续监控..."
        }
    }

    Start-Sleep -Seconds $checkInterval
}

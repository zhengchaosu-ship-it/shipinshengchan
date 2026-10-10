param(
    [ValidateRange(1, 65535)][int]$Port = 8502,
    [switch]$CheckOnly
)
$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../../..'))
$python = Join-Path $projectRoot '.venv-cuda-test/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw 'Missing existing XunFrame interpreter.'
}
# 员工入口仅限Private与本地子网，不开放Public/Domain。
$rule = @{
    Name = "XunFrame-LAN-TCP-$Port"
    DisplayName = "XunFrame LAN TCP $Port (LocalSubnet)"
    Direction = 'Inbound'
    Action = 'Allow'
    Enabled = 'True'
    Profile = 'Private'
    Protocol = 'TCP'
    LocalPort = $Port
    RemoteAddress = 'LocalSubnet'
    # venv/pythonw可由底层解释器承载；以TCP端口和本地子网限定，避免路径不匹配。
    Program = 'Any'
    EdgeTraversalPolicy = 'Block'
}
if ($CheckOnly) { $rule | ConvertTo-Json; exit 0 }
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Run setup_lan.ps1 once from an Administrator PowerShell. See LAN_ACCESS.md.'
}
# 重复执行更新同一规则；不修改网络类别、其他规则或关闭防火墙。
$existing = Get-NetFirewallRule -Name $rule.Name -ErrorAction SilentlyContinue
if ($existing) { Set-NetFirewallRule @rule | Out-Null }
else { New-NetFirewallRule @rule | Out-Null }
Get-NetFirewallRule -Name $rule.Name | Select-Object Name, Enabled, Direction, Action, Profile

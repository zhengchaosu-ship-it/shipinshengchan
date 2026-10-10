param([Parameter(Mandatory=$true)][string]$BackupPath)
$ErrorActionPreference='Stop'
$path='HKLM:\SYSTEM\CurrentControlSet\Control\Lsa'
$old=Get-ItemProperty $path
$config=Get-SmbServerConfiguration
if(-not(Test-Path -LiteralPath $BackupPath)){
    @{ForceGuest=$old.forceguest;EnableAuthenticateUserSharing=$config.EnableAuthenticateUserSharing;
      at=(Get-Date).ToString('o');reason='Dedicated worker credentials must not map to Guest'} |
        ConvertTo-Json | Set-Content -LiteralPath $BackupPath -Encoding utf8
}
Set-ItemProperty -LiteralPath $path -Name forceguest -Type DWord -Value 0
Set-SmbServerConfiguration -EnableAuthenticateUserSharing $true -Force
# 仅认证策略，不重启LanmanServer、不启用不安全Guest、不关闭防火墙。
Get-ItemProperty $path | Select-Object forceguest | ConvertTo-Json
Get-SmbServerConfiguration | Select-Object EnableAuthenticateUserSharing | ConvertTo-Json

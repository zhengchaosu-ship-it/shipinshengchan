param([Parameter(Mandatory=$true)][string]$WorkerPublicKey,
      [Parameter(Mandatory=$true)][string]$SecretRoot,
      [Parameter(Mandatory=$true)][string]$AssetsRoot,
      [Parameter(Mandatory=$true)][string]$PackagesRoot,
      [Parameter(Mandatory=$true)][string]$OutputRoot,
      [Parameter(Mandatory=$true)][string]$WorkerIP,
      [int]$ApiPort=8766)
$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Security
$account='XunZhenRender'
if(Get-LocalUser -Name $account -ErrorAction SilentlyContinue){throw 'WORKER_ACCOUNT_EXISTS_REVIEW_NO_PASSWORD_RESET'}
New-Item -ItemType Directory -Path $SecretRoot,$OutputRoot -Force | Out-Null
$rng=[Security.Cryptography.RandomNumberGenerator]::Create()
$bytes=New-Object byte[] 32
$rng.GetBytes($bytes)
$password=[Convert]::ToBase64String($bytes)+'aA1!'
$rng.GetBytes($bytes)
$token=[Convert]::ToBase64String($bytes)
$rng.Dispose()
$secure=ConvertTo-SecureString $password -AsPlainText -Force
New-LocalUser -Name $account -Password $secure -Description 'LAN Render dedicated SMB account, no GUI jobs' -AccountNeverExpires -PasswordNeverExpires | Out-Null
$server=[Net.Dns]::GetHostName()
$user=$server+'\'+$account
$sid=(Get-LocalUser -Name $account).SID.Value
# 仅向显式三个共享根增加权限，既有素材/任务内容不重写、不复制。
& icacls.exe $AssetsRoot /grant ('*'+$sid+':(OI)(CI)RX') | Out-Null
if($LASTEXITCODE){throw 'ASSET_ACL_FAILED'}
& icacls.exe $PackagesRoot /grant ('*'+$sid+':(OI)(CI)RX') | Out-Null
if($LASTEXITCODE){throw 'PACKAGE_ACL_FAILED'}
& icacls.exe $OutputRoot /grant ('*'+$sid+':(OI)(CI)M') | Out-Null
if($LASTEXITCODE){throw 'OUTPUT_ACL_FAILED'}
foreach($entry in @(@('StartupAssets',$AssetsRoot,'Read'),@('StartupTaskFiles',$PackagesRoot,'Read'),@('RenderOutput',$OutputRoot,'Change'))){
    if(Get-SmbShare -Name $entry[0] -ErrorAction SilentlyContinue){throw 'SHARE_EXISTS_REVIEW_NO_REPLACE'}
    if($entry[2] -eq 'Read'){
        New-SmbShare -Name $entry[0] -Path $entry[1] -ReadAccess $user -FullAccess 'BUILTIN\Administrators' -EncryptData $true | Out-Null
    }else{
        New-SmbShare -Name $entry[0] -Path $entry[1] -ChangeAccess $user -FullAccess 'BUILTIN\Administrators' -EncryptData $true | Out-Null
    }
}
# 将已确认家庭LAN标记Private；不改IP/DNS/路由，不关闭防火墙。
$network=Get-NetConnectionProfile | Where-Object {$_.IPv4Connectivity -ne 'Disconnected'}
if(@($network).Count -ne 1){throw 'NETWORK_PROFILE_AMBIGUOUS'}
Set-NetConnectionProfile -InterfaceIndex $network.InterfaceIndex -NetworkCategory Private
New-NetFirewallRule -Name 'XunZhen-LAN-Render-API' -DisplayName 'XunZhen LAN Render API private worker only' -Direction Inbound -Action Allow -Protocol TCP -LocalPort $ApiPort -RemoteAddress $WorkerIP -Profile Private -EdgeTraversalPolicy Block | Out-Null
New-NetFirewallRule -Name 'XunZhen-LAN-Render-SMB' -DisplayName 'XunZhen LAN Render SMB private worker only' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 445 -RemoteAddress $WorkerIP -Profile Private -EdgeTraversalPolicy Block | Out-Null
# 凭据DPAPI落盘；不打印明文、不进入参数/前端。
foreach($entry in @(@('worker_token.dpapi',$token),@('smb_password.dpapi',$password))){
    [IO.File]::WriteAllBytes((Join-Path $SecretRoot $entry[0]),[Security.Cryptography.ProtectedData]::Protect([Text.Encoding]::UTF8.GetBytes($entry[1]),$null,[Security.Cryptography.DataProtectionScope]::CurrentUser))
}
& icacls.exe $SecretRoot /inheritance:r /grant:r ('*'+[Security.Principal.WindowsIdentity]::GetCurrent().User.Value+':(OI)(CI)F') '*S-1-5-18:(OI)(CI)F' | Out-Null
$rsa=New-Object Security.Cryptography.RSACryptoServiceProvider
$rsa.PersistKeyInCsp=$false
$rsa.FromXmlString([IO.File]::ReadAllText($WorkerPublicKey))
$data=@{server=$server;user=$user;password=$password;token=$token}|ConvertTo-Json -Compress
$encrypted=$rsa.Encrypt([Text.Encoding]::UTF8.GetBytes($data),$true)
$rsa.Dispose()
[Convert]::ToBase64String($encrypted)

param([Parameter(Mandatory=$true)][string]$PublicKey,[Parameter(Mandatory=$true)][string]$SecretRoot)
$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Security
function Read-Secret([string]$Name){
    $bytes=[IO.File]::ReadAllBytes((Join-Path $SecretRoot $Name))
    [Text.Encoding]::UTF8.GetString([Security.Cryptography.ProtectedData]::Unprotect($bytes,$null,[Security.Cryptography.DataProtectionScope]::CurrentUser))
}
$server=[Net.Dns]::GetHostName()
$payload=@{server=$server;user=$server+'\XunZhenRender';password=(Read-Secret 'smb_password.dpapi');token=(Read-Secret 'worker_token.dpapi')}|ConvertTo-Json -Compress
$rsa=New-Object Security.Cryptography.RSACryptoServiceProvider
$rsa.PersistKeyInCsp=$false
$rsa.FromXmlString([IO.File]::ReadAllText($PublicKey))
$encrypted=$rsa.Encrypt([Text.Encoding]::UTF8.GetBytes($payload),$true)
$rsa.Dispose()
[Convert]::ToBase64String($encrypted)

param([Parameter(Mandatory=$true)][string]$Root)
$ErrorActionPreference='Stop'
New-Item -ItemType Directory -Path $Root -Force | Out-Null
Add-Type -AssemblyName System.Security
$privatePath=Join-Path $Root 'bootstrap_rsa.dpapi'
if(Test-Path -LiteralPath $privatePath){throw 'BOOTSTRAP_KEY_EXISTS_NO_REPLACE'}
$rsa=New-Object Security.Cryptography.RSACryptoServiceProvider(4096)
$rsa.PersistKeyInCsp=$false
$bytes=[Text.Encoding]::UTF8.GetBytes($rsa.ToXmlString($true))
[IO.File]::WriteAllBytes($privatePath,[Security.Cryptography.ProtectedData]::Protect($bytes,$null,[Security.Cryptography.DataProtectionScope]::CurrentUser))
$public=$rsa.ToXmlString($false)
$rsa.Dispose()
$public

param([string]$Source='\\PC-20260617GEOP\RenderOutput\2060_yxer_provision')
$ErrorActionPreference='Stop'
if([Environment]::MachineName -ne 'DESKTOP-9VQ76D3'){throw '2060_HOST_REQUIRED'}
$root='D:\JianyingRenderWorker'
$destination=Join-Path $root 'Tools\yxer'
New-Item -ItemType Directory -Path $destination -Force | Out-Null
Get-ChildItem -LiteralPath (Join-Path $Source 'cli') | ForEach-Object { Copy-Item -LiteralPath $_.FullName -Destination $destination -Recurse -Force }
Copy-Item -LiteralPath (Join-Path $destination 'bin-native\yxer.exe') -Destination (Join-Path $destination 'yxer.exe') -Force
$profile=[Environment]::GetFolderPath('UserProfile')
$configFolder=Join-Path $profile '.yxer'
New-Item -ItemType Directory -Path $configFolder -Force | Out-Null
$configPath=Join-Path $configFolder 'config.json'
if(Test-Path -LiteralPath $configPath){throw 'EXISTING_CONFIG_REVIEW_REQUIRED'}
Add-Type -AssemblyName System.Security
$secretRoot=Join-Path $root 'Resident\secrets'
$private=[Security.Cryptography.ProtectedData]::Unprotect([IO.File]::ReadAllBytes((Join-Path $secretRoot 'bootstrap_rsa.dpapi')),$null,[Security.Cryptography.DataProtectionScope]::CurrentUser)
$rsa=New-Object Security.Cryptography.RSACryptoServiceProvider
$rsa.PersistKeyInCsp=$false
$rsa.FromXmlString([Text.Encoding]::UTF8.GetString($private))
$plain=$rsa.Decrypt([Convert]::FromBase64String([IO.File]::ReadAllText((Join-Path $Source 'api_config.rsa.enc'))),$true)
$rsa.Dispose()
$config=[Text.Encoding]::UTF8.GetString($plain) | ConvertFrom-Json
$app=Get-Content -LiteralPath (Join-Path ([Environment]::GetFolderPath('ApplicationData')) '蚁小二4.0\config.json') -Raw -Encoding UTF8 | ConvertFrom-Json
if(-not $app.deviceId){throw 'LOCAL_CLIENT_DEVICE_ID_REQUIRED'}
$config | Add-Member -NotePropertyName localPublishClientId -NotePropertyValue $app.deviceId
[IO.File]::WriteAllText($configPath,($config | ConvertTo-Json -Depth 5),(New-Object Text.UTF8Encoding($false)))
& icacls.exe $configFolder /inheritance:r /grant:r ('*'+[Security.Principal.WindowsIdentity]::GetCurrent().User.Value+':(OI)(CI)F') '*S-1-5-18:(OI)(CI)F' | Out-Null
$exe=Join-Path $destination 'yxer.exe'
& $exe doctor
if($LASTEXITCODE -ne 0){throw 'LOCAL_DOCTOR_FAILED'}
'LOCAL_YXER_CONFIGURED'

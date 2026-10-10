$ErrorActionPreference='Stop'
$root=Split-Path $PSScriptRoot
$destination=Join-Path $root 'outputs\lan_render\2060_yxer_provision'
New-Item -ItemType Directory -Path $destination -Force | Out-Null
$cli=Join-Path $env:USERPROFILE '.local\node_modules\@yixiaoermail\cli'
Copy-Item -LiteralPath $cli -Destination $destination -Recurse -Force
$config=Get-Content -LiteralPath (Join-Path $env:USERPROFILE '.yxer\config.json') -Encoding UTF8 -Raw | ConvertFrom-Json
# 只将API配置加密给现有2060 DPAPI保护的RSA密钥；不复制Server clientId。
$value=@{apiKey=$config.apiKey;apiUrl=$config.apiUrl} | ConvertTo-Json -Compress
$rsa=New-Object Security.Cryptography.RSACryptoServiceProvider
$rsa.PersistKeyInCsp=$false
$rsa.FromXmlString([IO.File]::ReadAllText((Join-Path $root 'startup_render\runtime\lan_resident_v1\worker_public.xml')))
[IO.File]::WriteAllText((Join-Path $destination 'api_config.rsa.enc'),[Convert]::ToBase64String($rsa.Encrypt([Text.Encoding]::UTF8.GetBytes($value),$true)))
$rsa.Dispose()
'ENCRYPTED_PROVISION_READY'

param([Parameter(Mandatory=$true)][string]$Root,[Parameter(Mandatory=$true)][string]$Envelope,
      [string]$ServerIP)
$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Security
$private=[Security.Cryptography.ProtectedData]::Unprotect([IO.File]::ReadAllBytes((Join-Path $Root 'bootstrap_rsa.dpapi')),$null,[Security.Cryptography.DataProtectionScope]::CurrentUser)
$rsa=New-Object Security.Cryptography.RSACryptoServiceProvider
$rsa.PersistKeyInCsp=$false
$rsa.FromXmlString([Text.Encoding]::UTF8.GetString($private))
$decoded=$rsa.Decrypt([Convert]::FromBase64String([IO.File]::ReadAllText($Envelope).Trim()),$true)
$rsa.Dispose()
$secret=[Text.Encoding]::UTF8.GetString($decoded)|ConvertFrom-Json
[IO.File]::WriteAllBytes((Join-Path $Root 'worker_token.dpapi'),[Security.Cryptography.ProtectedData]::Protect([Text.Encoding]::UTF8.GetBytes($secret.token),$null,[Security.Cryptography.DataProtectionScope]::CurrentUser))
Add-Type @'
using System;
using System.Runtime.InteropServices;
public class XunZhenCredential {
 [StructLayout(LayoutKind.Sequential,CharSet=CharSet.Unicode)]
 public struct Credential { public uint Flags; public uint Type; public string TargetName; public string Comment;
 public System.Runtime.InteropServices.ComTypes.FILETIME LastWritten; public uint CredentialBlobSize;
 public IntPtr CredentialBlob; public uint Persist; public uint AttributeCount; public IntPtr Attributes;
 public string TargetAlias; public string UserName; }
 [DllImport("advapi32.dll",EntryPoint="CredWriteW",CharSet=CharSet.Unicode,SetLastError=true)]
 public static extern bool Write(ref Credential credential,uint flags);
}
'@
$blob=[Text.Encoding]::Unicode.GetBytes($secret.password)
$ptr=[Runtime.InteropServices.Marshal]::AllocHGlobal($blob.Length)
try{
    [Runtime.InteropServices.Marshal]::Copy($blob,0,$ptr,$blob.Length)
    $credential=New-Object XunZhenCredential+Credential
    $credential.Type=2
    $credential.TargetName=$secret.server
    $credential.UserName=$secret.user
    $credential.CredentialBlobSize=$blob.Length
    $credential.CredentialBlob=$ptr
    $credential.Persist=2
    if(-not [XunZhenCredential]::Write([ref]$credential,0)){throw 'SMB_CREDENTIAL_WRITE_FAILED'}
    if($ServerIP){
        $credential.TargetName=$ServerIP
        if(-not [XunZhenCredential]::Write([ref]$credential,0)){throw 'SMB_IP_CREDENTIAL_WRITE_FAILED'}
    }
}finally{[Runtime.InteropServices.Marshal]::FreeHGlobal($ptr)}
& icacls.exe $Root /inheritance:r /grant:r ('*'+[Security.Principal.WindowsIdentity]::GetCurrent().User.Value+':(OI)(CI)F') '*S-1-5-18:(OI)(CI)F' | Out-Null
# 客户端只发起出站SMB，不开放入站共享。Private入站边界在服务器配置。
# 固定GUI用户无需管理员权限；不为客户端网卡强制提权/变更配置。
'WORKER_SECRETS_INSTALLED_DPAPI_CREDENTIAL_MANAGER'

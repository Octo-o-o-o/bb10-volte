param([Parameter(Mandatory=$true)][string]$Path)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
Import-Module (Join-Path $PSHOME 'Modules\Microsoft.PowerShell.Security\Microsoft.PowerShell.Security.psd1') -Force
Import-Module (Join-Path $PSHOME 'Modules\Microsoft.PowerShell.Utility\Microsoft.PowerShell.Utility.psd1') -Force
$signature = Get-AuthenticodeSignature -LiteralPath $Path
if ($signature.Status -ne 'Valid') {
    throw ('The source signature is not valid: ' + [string]$signature.Status + ' (' + [string]$signature.StatusMessage + ')')
}
[pscustomobject]@{Status=[string]$signature.Status; Signer=$signature.SignerCertificate.Subject} | ConvertTo-Json -Compress

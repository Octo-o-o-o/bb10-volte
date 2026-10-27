#requires -RunAsAdministrator
# Windows PowerShell 5.1. Installs only the separately prepared and verified kit.
$ErrorActionPreference = 'Stop'
foreach ($moduleName in @('Microsoft.PowerShell.Security','Microsoft.PowerShell.Management','Microsoft.PowerShell.Utility')) {
    Import-Module (Join-Path $PSHOME ('Modules\'+$moduleName+'\'+$moduleName+'.psd1')) -Force
}
$projectPath = Split-Path -Parent $PSScriptRoot
$kitPath = Join-Path $projectPath 'private\windows-usb'
$spec = Get-Content -LiteralPath (Join-Path $projectPath 'materials\usb-drivers.json') -Raw | ConvertFrom-Json
$bundlePath = Join-Path $kitPath 'package\BlackBerry-USBDrivers-5.0.0.2.exe'
$msiPath = Join-Path $kitPath 'USBInstallerMSIx64.msi'
if (-not [Environment]::Is64BitOperatingSystem) { throw 'This recipe requires 64-bit Windows.' }
if ((Get-FileHash -LiteralPath $bundlePath -Algorithm SHA256).Hash -ne $spec.bundle_sha256) { throw 'Bundle hash mismatch.' }
if ((Get-AuthenticodeSignature -LiteralPath $bundlePath).Status -ne 'Valid') { throw 'Bundle signature mismatch.' }
if ((Get-FileHash -LiteralPath $msiPath -Algorithm SHA256).Hash -ne $spec.msi_sha256) { throw 'MSI hash mismatch.' }
$driverPath = Join-Path $kitPath 'rim-usb'
foreach ($entry in $spec.driver_files.PSObject.Properties) {
    if ((Get-FileHash -LiteralPath (Join-Path $driverPath $entry.Name) -Algorithm SHA256).Hash -ne $entry.Value) {
        throw ('Driver changed: '+$entry.Name)
    }
}
if ((Get-AuthenticodeSignature -LiteralPath (Join-Path $driverPath 'rimusbnt.cat')).Status -ne 'Valid') { throw 'Catalog signature mismatch.' }
# The old vendor MSI contains unconditional process-stop custom actions.
foreach ($processName in @('nginx','PeerManager','tunmgr','RimDeviceManager','RIMDEV~1')) {
    if (Get-Process -Name $processName -ErrorAction SilentlyContinue) {
        throw ('The vendor installer could interrupt this existing process: '+$processName)
    }
}
& "$env:SystemRoot\System32\pnputil.exe" /add-driver (Join-Path $driverPath 'RimUsbNT.inf') /install
if ($LASTEXITCODE -notin @(0,3010)) { throw ('pnputil exit: '+$LASTEXITCODE) }
$installLog = Join-Path $kitPath 'device-manager-install.log'
$arguments = '/i "'+$msiPath+'" /qn /norestart REBOOT=ReallySuppress /L*v "'+$installLog+'"'
$process = Start-Process -FilePath "$env:SystemRoot\System32\msiexec.exe" -ArgumentList $arguments -WindowStyle Hidden -Wait -PassThru
if ($process.ExitCode -notin @(0,3010)) { throw ('MSI exit: '+$process.ExitCode) }
Write-Output ('InstallerExitCode='+$process.ExitCode)
Get-Service -Name 'BlackBerry Device Manager' -ErrorAction SilentlyContinue | Select-Object Name,Status,StartType

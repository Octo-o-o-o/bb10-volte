#requires -RunAsAdministrator
# Windows PowerShell 5.1. Installs only the separately prepared and verified kit.
param([string]$PreparedKit, [string]$SpecPath)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
foreach ($moduleName in @('Microsoft.PowerShell.Security','Microsoft.PowerShell.Management','Microsoft.PowerShell.Utility')) {
    Import-Module (Join-Path $PSHOME ('Modules\'+$moduleName+'\'+$moduleName+'.psd1')) -Force
}
$projectPath = Split-Path -Parent $PSScriptRoot
$kitPath = if ($PreparedKit) { $PreparedKit } else { Join-Path $projectPath 'private\windows-usb' }
$manifestPath = if ($SpecPath) { $SpecPath } else { Join-Path $projectPath 'materials\usb-drivers.json' }
$resultPath = Join-Path $kitPath 'driver-install-result.json'
$status = [ordered]@{
    step = 'init'
    exit_code = 1
    pnputil_add_exit = $null
    pnputil_install_exit = $null
    msi_exit = $null
    blocked_process = $null
    service_present = $false
    error_message = $null
}
function Save-DriverResult {
    try {
        if (Test-Path -LiteralPath $kitPath) {
            $json = $status | ConvertTo-Json -Compress
            [System.IO.File]::WriteAllText($resultPath, $json, [System.Text.UTF8Encoding]::new($false))
        }
    } catch {}
}
try {
    $status.step = 'verify_inputs'
    $spec = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $bundlePath = Join-Path $kitPath 'package\BlackBerry-USBDrivers-5.0.0.2.exe'
    $msiPath = Join-Path $kitPath 'USBInstallerMSIx64.msi'
    if (-not [Environment]::Is64BitOperatingSystem) { throw 'This recipe requires 64-bit Windows.' }
    if ((Get-FileHash -LiteralPath $bundlePath -Algorithm SHA256).Hash -ne $spec.bundle_sha256) { throw 'Bundle hash mismatch.' }
    $bundleSig = Get-AuthenticodeSignature -LiteralPath $bundlePath
    if ($bundleSig.Status -ne 'Valid') { throw ('Bundle signature mismatch: ' + $bundleSig.Status) }
    if ((Get-FileHash -LiteralPath $msiPath -Algorithm SHA256).Hash -ne $spec.msi_sha256) { throw 'MSI hash mismatch.' }
    $driverPath = Join-Path $kitPath 'rim-usb'
    foreach ($entry in $spec.driver_files.PSObject.Properties) {
        if ((Get-FileHash -LiteralPath (Join-Path $driverPath $entry.Name) -Algorithm SHA256).Hash -ne $entry.Value) {
            throw ('Driver changed: '+$entry.Name)
        }
    }
    $catSig = Get-AuthenticodeSignature -LiteralPath (Join-Path $driverPath 'rimusbnt.cat')
    if ($catSig.Status -ne 'Valid') { throw ('Catalog signature mismatch: ' + $catSig.Status) }

    $status.step = 'check_processes'
    # The old vendor MSI contains unconditional process-stop custom actions.
    foreach ($processName in @('nginx','PeerManager','tunmgr','RimDeviceManager','RIMDEV~1')) {
        if (Get-Process -Name $processName -ErrorAction SilentlyContinue) {
            $status.blocked_process = $processName
            throw ('The vendor installer could interrupt this existing process: '+$processName)
        }
    }

    $status.step = 'pnputil_add'
    $infPath = Join-Path $driverPath 'RimUsbNT.inf'
    # Stage into Windows DriverStore first (succeeds even when no Bootrom device is plugged in).
    & "$env:SystemRoot\System32\pnputil.exe" /add-driver $infPath | Out-Null
    $addExit = $LASTEXITCODE
    $status.pnputil_add_exit = $addExit
    if ($addExit -notin @(0,3010,259)) { throw ('pnputil add exit: '+$addExit) }

    $status.step = 'pnputil_install'
    # Attempt live install if a matching device is attached; 259 (ERROR_NO_MORE_ITEMS)
    # is expected on Windows 10/11 when no Bootrom device is attached or driver is up to date.
    & "$env:SystemRoot\System32\pnputil.exe" /add-driver $infPath /install | Out-Null
    $driverExit = $LASTEXITCODE
    $status.pnputil_install_exit = $driverExit
    if ($driverExit -notin @(0,3010,259)) { throw ('pnputil install exit: '+$driverExit) }

    $status.step = 'msi_install'
    $installLog = Join-Path $kitPath 'device-manager-install.log'
    $arguments = '/i "'+$msiPath+'" /qn /norestart REBOOT=ReallySuppress /L*v "'+$installLog+'"'
    $process = Start-Process -FilePath "$env:SystemRoot\System32\msiexec.exe" -ArgumentList $arguments -WindowStyle Hidden -Wait -PassThru
    $msiExit = $process.ExitCode
    $status.msi_exit = $msiExit
    $bdm = Get-Service -Name 'BlackBerry Device Manager' -ErrorAction SilentlyContinue
    $status.service_present = ($null -ne $bdm)
    if ($msiExit -eq 1638 -and $status.service_present) {
        # Another compatible version of BlackBerry Device Manager is already installed.
        $msiExit = 0
    }
    if ($msiExit -notin @(0,3010)) { throw ('MSI exit: '+$msiExit) }

    $status.step = 'complete'
    $finalCode = if ($msiExit -eq 3010 -or $driverExit -eq 3010 -or $addExit -eq 3010) { 3010 } else { 0 }
    $status.exit_code = $finalCode
    Save-DriverResult
    Write-Output ('InstallerExitCode='+$msiExit)
    if ($bdm) { $bdm | Select-Object Name,Status,StartType }
    exit $finalCode
} catch {
    $status.error_message = $_.Exception.Message
    if ($status.exit_code -eq 0) { $status.exit_code = 1 }
    Save-DriverResult
    Write-Error $_.Exception.Message
    exit 1
}

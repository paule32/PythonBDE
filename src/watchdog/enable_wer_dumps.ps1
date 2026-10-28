# Run explicitly from an elevated PowerShell if you want WER minidumps.
# Windows Error Reporting stores dumps in %%LOCALAPPDATA%%\CrashDumps by default.
param([switch]$FullDump)
$kind = if ($FullDump) { 2 } else { 1 }
foreach ($exe in @('pythonw.exe', 'python.exe')) {
    $path = "HKLM:\SOFTWARE\Microsoft\Windows\Windows Error Reporting\LocalDumps\$exe"
    New-Item -Path $path -Force | Out-Null
    New-ItemProperty -Path $path -Name DumpType -PropertyType DWord -Value $kind -Force | Out-Null
    New-ItemProperty -Path $path -Name DumpCount -PropertyType DWord -Value 10 -Force | Out-Null
    Write-Output "WER configured: $exe (DumpType $kind)"
}
Write-Warning 'Die Regeln gelten fuer ALLE Prozesse mit diesen Namen; Dumps koennen sensible Daten enthalten.'

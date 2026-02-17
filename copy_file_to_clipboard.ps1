param([string]$FilePath)
Add-Type -AssemblyName System.Windows.Forms
$file = New-Object System.Collections.Specialized.StringCollection
$file.Add($FilePath)
[System.Windows.Forms.Clipboard]::SetFileDropList($file)
Write-Host "File copied to clipboard: $FilePath"

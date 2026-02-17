param(
    [Parameter(Mandatory=$true)]
    [string]$FilePath,
    [switch]$AsImage
)

Add-Type -AssemblyName System.Windows.Forms

if ($AsImage) {
    Add-Type -AssemblyName System.Drawing
    $img = [System.Drawing.Image]::FromFile($FilePath)
    [System.Windows.Forms.Clipboard]::SetImage($img)
    $img.Dispose()
    Write-Host "Image copied to clipboard: $FilePath"
} else {
    $file = New-Object System.Collections.Specialized.StringCollection
    $file.Add($FilePath)
    [System.Windows.Forms.Clipboard]::SetFileDropList($file)
    Write-Host "File copied to clipboard: $FilePath"
}

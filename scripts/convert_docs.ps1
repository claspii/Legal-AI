param([string]$DocsDir)

$word = New-Object -ComObject Word.Application
$word.Visible = $false
$word.DisplayAlerts = 0

$docFiles = Get-ChildItem -Path $DocsDir -Filter "*.doc" | Where-Object { $_.Extension -eq ".doc" }

foreach ($file in $docFiles) {
    $outPath = Join-Path $DocsDir ($file.BaseName + ".txt")
    Write-Host "Converting: $($file.Name) -> $($file.BaseName).txt"
    try {
        $doc = $word.Documents.Open($file.FullName)
        $text = $doc.Content.Text
        [System.IO.File]::WriteAllText($outPath, $text, [System.Text.Encoding]::UTF8)
        $doc.Close($false)
        Write-Host "  OK ($($text.Length) chars)"
    } catch {
        Write-Host "  FAILED: $_"
    }
}

$word.Quit()
Write-Host "Done."

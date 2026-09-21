$ErrorActionPreference = 'Stop'

$templateDocx = 'G:\VSCODE_Save_Files\TRANSLATE\.qa_pages\template_converted.docx'
$reportPath = 'C:\Users\kalianna\Desktop\实习报告\集中实习报告最终版.docx'
$outputPath = 'C:\Users\kalianna\Desktop\实习报告\集中实习报告最终版_已替换首尾页.docx'

$wdGoToPage = 1
$wdGoToAbsolute = 1
$wdFormatOriginalFormatting = 16

function Get-PageStart($doc, [int]$pageNumber) {
    return $doc.GoTo($wdGoToPage, $wdGoToAbsolute, $pageNumber).Start
}

$word = $null
$template = $null
$report = $null
try {
    $word = New-Object -ComObject Word.Application
    $word.Visible = $false
    $word.DisplayAlerts = 0

    if (Test-Path -LiteralPath $outputPath) { Remove-Item -LiteralPath $outputPath -Force }
    Copy-Item -LiteralPath $templateDocx -Destination $outputPath

    $template = $word.Documents.Open($outputPath, $false, $false)
    $report = $word.Documents.Open($reportPath, $false, $true)
    $template.TrackRevisions = $false

    $templatePages = $template.ComputeStatistics(2)
    $reportPages = $report.ComputeStatistics(2)

    # Keep template page 1 and its final page; remove template pages in between.
    $removeStart = Get-PageStart $template 2
    $lastTemplateStart = Get-PageStart $template $templatePages
    $template.Range($removeStart, $lastTemplateStart).Delete() | Out-Null
    $template.Repaginate()

    # Copy only the report body (excluding its existing first and last pages).
    $bodyStart = Get-PageStart $report 2
    $bodyEnd = Get-PageStart $report $reportPages
    $report.Range($bodyStart, $bodyEnd).Copy()

    # Insert before the retained final template page, preserving source formatting and media.
    $insertAt = Get-PageStart $template 2
    $destination = $template.Range($insertAt, $insertAt)
    $destination.PasteAndFormat($wdFormatOriginalFormatting)

    $template.Repaginate()
    $pagesAfter = $template.ComputeStatistics(2)
    $template.Save()

    [pscustomobject]@{
        TemplatePages = $templatePages
        ReportPages = $reportPages
        OutputPages = $pagesAfter
        OutputPath = $outputPath
    } | ConvertTo-Json
}
finally {
    if ($report) { $report.Close($false); [System.Runtime.InteropServices.Marshal]::ReleaseComObject($report) | Out-Null }
    if ($template) { $template.Close($false); [System.Runtime.InteropServices.Marshal]::ReleaseComObject($template) | Out-Null }
    if ($word) { $word.Quit(); [System.Runtime.InteropServices.Marshal]::ReleaseComObject($word) | Out-Null }
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}

$ErrorActionPreference = 'Stop'

$folder = 'C:\Users\kalianna\Desktop\实习报告'
$templatePath = Join-Path $folder '东南大学实习报告模板.doc'
$reportPath = Join-Path $folder '集中实习报告最终版.docx'
$outputPath = Join-Path $folder '集中实习报告最终版_已替换首尾页.docx'

$wdGoToPage = 1
$wdGoToAbsolute = 1
$wdCollapseStart = 1

function Get-PageStart($doc, [int]$pageNumber) {
    return $doc.GoTo($wdGoToPage, $wdGoToAbsolute, $pageNumber).Start
}

function Get-PageRange($doc, [int]$pageNumber) {
    $pageCount = $doc.ComputeStatistics(2)
    $start = Get-PageStart $doc $pageNumber
    if ($pageNumber -lt $pageCount) {
        $end = Get-PageStart $doc ($pageNumber + 1)
    } else {
        $end = $doc.Content.End
    }
    return $doc.Range($start, $end)
}

$word = $null
$template = $null
$report = $null
try {
    $word = New-Object -ComObject Word.Application
    $word.Visible = $false
    $word.DisplayAlerts = 0

    $template = $word.Documents.Open($templatePath, $false, $true)
    $templatePages = $template.ComputeStatistics(2)

    if (Test-Path -LiteralPath $outputPath) { Remove-Item -LiteralPath $outputPath -Force }
    Copy-Item -LiteralPath $reportPath -Destination $outputPath
    $report = $word.Documents.Open($outputPath, $false, $false)
    $report.TrackRevisions = $false
    $reportPagesBefore = $report.ComputeStatistics(2)

    # Replace the last page first so the first-page edit cannot affect its original location.
    $templateLast = Get-PageRange $template $templatePages
    $reportLast = Get-PageRange $report $reportPagesBefore
    $reportLast.FormattedText = $templateLast.FormattedText

    # Recalculate page locations, then replace the first page.
    $report.Repaginate()
    $templateFirst = Get-PageRange $template 1
    $reportFirst = Get-PageRange $report 1
    $reportFirst.FormattedText = $templateFirst.FormattedText

    $report.Save()
    $report.Repaginate()
    $reportPagesAfter = $report.ComputeStatistics(2)

    [pscustomobject]@{
        TemplatePages = $templatePages
        ReportPagesBefore = $reportPagesBefore
        ReportPagesAfter = $reportPagesAfter
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

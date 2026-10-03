param([ValidatePattern('^\d+\.\d+(\.\d+)?$')][string]$Version = '1.4.0')
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
& .venv\Scripts\python.exe -m PyInstaller --noconfirm --distpath "dist\release-$Version" ScreenLingo.spec
if ($LASTEXITCODE -ne 0) { throw 'Build failed' }
Copy-Item -LiteralPath 'RELEASE_README.txt' -Destination "dist\release-$Version\ScreenLingo\README.txt" -Force
Copy-Item -LiteralPath "RELEASE_$Version.md" -Destination "dist\release-$Version\ScreenLingo\CHANGELOG.md" -Force
& .venv\Scripts\python.exe -c "import shutil; shutil.make_archive('dist/ScreenLingo-$Version-Windows-x64', 'zip', 'dist/release-$Version', 'ScreenLingo')"
if ($LASTEXITCODE -ne 0) { throw 'Archive failed' }

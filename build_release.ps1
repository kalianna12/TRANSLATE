$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
& .venv\Scripts\python.exe -m PyInstaller --noconfirm --distpath dist\release-1.2 ScreenLingo.spec
if ($LASTEXITCODE -ne 0) { throw 'Build failed' }
Copy-Item -LiteralPath 'RELEASE_README.txt' -Destination 'dist\release-1.2\ScreenLingo\README.txt' -Force
Compress-Archive -Path 'dist\release-1.2\ScreenLingo' -DestinationPath 'dist\ScreenLingo-1.2-Windows-x64.zip' -Force

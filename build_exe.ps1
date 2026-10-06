$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $ProjectRoot
try {
    $Python = Get-Command python -ErrorAction SilentlyContinue
    if (-not $Python) {
        throw "Python was not found. Install Python on the build computer and install requirements.txt."
    }

    & python -m PyInstaller --noconfirm --clean (Join-Path $ProjectRoot "Daily.spec")
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed with exit code $LASTEXITCODE."
    }

    Write-Host "Build complete: $ProjectRoot\dist\Daily\Daily.exe"
    $Compiler = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    $CompilerPath = if ($Compiler) { $Compiler.Source } else { $null }
    if (-not $CompilerPath) {
        $Candidates = @(
            (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"),
            (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe")
        )
        if (${env:ProgramFiles(x86)}) {
            $Candidates += Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"
        }
        $CompilerPath = $Candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
    }
    if ($CompilerPath) {
        & $CompilerPath (Join-Path $ProjectRoot "installer\Daily.iss")
        if ($LASTEXITCODE -ne 0) {
            throw "Inno Setup failed with exit code $LASTEXITCODE."
        }
    }
    else {
        Write-Host "Inno Setup was not found. Run build_installer.bat after installing Inno Setup."
    }
}
finally {
    Pop-Location
}

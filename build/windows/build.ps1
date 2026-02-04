Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path -Path $PSScriptRoot -ChildPath "..\\..")).Path
$distPath = Join-Path $repoRoot "dist"
$workPath = Join-Path -Path $repoRoot -ChildPath "build\\pyinstaller"
$sourcePath = Join-Path $repoRoot "src"

$pyinstallerArgs = @(
    "--noconfirm",
    "--clean",
    "--onefile",
    "--console",
    "--name",
    "pyrigol-tui",
    "--paths",
    $sourcePath,
    "--distpath",
    $distPath,
    "--workpath",
    $workPath,
    "--collect-submodules",
    "pyvisa",
    "src/pyrigol/app/tui.py"
)

Push-Location $repoRoot
try {
    if (Get-Command uv -ErrorAction SilentlyContinue) {
        & uv run pyinstaller @pyinstallerArgs
    } elseif (Get-Command pyinstaller -ErrorAction SilentlyContinue) {
        & pyinstaller @pyinstallerArgs
    } else {
        throw "pyinstaller was not found. Install it with: uv sync --group build"
    }

    $exePath = Join-Path $distPath "pyrigol-tui.exe"
    if (-not (Test-Path $exePath)) {
        throw "Build completed but $exePath was not found."
    }

    Write-Host "Built: $exePath"
} finally {
    Pop-Location
}

param(
    [string]$InstallDir = ".tools/obscura"
)

$ErrorActionPreference = "Stop"

$repo = "h4ckf0r0day/obscura"
$headers = @{ "User-Agent" = "TitanShift" }

$resolvedInstallDir = [System.IO.Path]::GetFullPath($InstallDir)
$tempRoot = Join-Path $env:TEMP ("titantshift-obscura-" + [Guid]::NewGuid().ToString("N"))
$zipPath = Join-Path $tempRoot "obscura.zip"
$extractDir = Join-Path $tempRoot "extract"

New-Item -ItemType Directory -Force -Path $resolvedInstallDir | Out-Null
New-Item -ItemType Directory -Force -Path $extractDir | Out-Null

try {
    $release = Invoke-RestMethod -Uri ("https://api.github.com/repos/{0}/releases/latest" -f $repo) -Headers $headers
    $asset = $release.assets | Where-Object { $_.name -like "*windows*.zip" } | Select-Object -First 1

    if (-not $asset) {
        throw "No Windows zip asset found in latest Obscura release."
    }

    Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $zipPath -UseBasicParsing
    Expand-Archive -Path $zipPath -DestinationPath $extractDir -Force

    $exe = Get-ChildItem -Path $extractDir -Filter "obscura.exe" -Recurse -File | Select-Object -First 1
    if (-not $exe) {
        throw "Download completed, but obscura.exe was not found in the release archive."
    }

    Copy-Item -Path (Join-Path $exe.Directory.FullName "*") -Destination $resolvedInstallDir -Recurse -Force

    $installedExe = Join-Path $resolvedInstallDir "obscura.exe"
    if (-not (Test-Path $installedExe)) {
        throw "Install copy finished, but obscura.exe is missing from install directory."
    }

    Write-Output "ok=true"
    Write-Output ("install_dir={0}" -f $resolvedInstallDir)
    Write-Output ("exe_path={0}" -f $installedExe)
}
finally {
    if (Test-Path $tempRoot) {
        Remove-Item -Path $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}

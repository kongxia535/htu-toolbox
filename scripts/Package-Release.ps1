[CmdletBinding()]
param(
    [string]$OutputPath
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$distDirectory = Join-Path $repositoryRoot 'dist'

if ([string]::IsNullOrWhiteSpace($OutputPath)) {
    $OutputPath = Join-Path $distDirectory 'htu-toolbox-community.zip'
}

$outputFullPath = [IO.Path]::GetFullPath($OutputPath)
$distFullPath = [IO.Path]::GetFullPath($distDirectory)
if (-not $outputFullPath.StartsWith($distFullPath, [StringComparison]::OrdinalIgnoreCase)) {
    throw "OutputPath must stay inside: $distFullPath"
}

if (-not (Test-Path -LiteralPath $distDirectory)) {
    New-Item -ItemType Directory -Path $distDirectory -Force | Out-Null
}

$tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$stageDirectory = Join-Path $tempRoot ('htu-toolbox-release-' + [Guid]::NewGuid().ToString('N'))

function Copy-ProjectItem {
    param(
        [string]$RelativePath,
        [switch]$Recurse
    )

    $source = Join-Path $repositoryRoot $RelativePath
    if (-not (Test-Path -LiteralPath $source)) {
        return
    }

    $destination = Join-Path $stageDirectory $RelativePath
    $destinationParent = Split-Path -Parent $destination
    if (-not (Test-Path -LiteralPath $destinationParent)) {
        New-Item -ItemType Directory -Path $destinationParent -Force | Out-Null
    }

    if ($Recurse) {
        Copy-Item -LiteralPath $source -Destination $destination -Recurse -Force
    }
    else {
        Copy-Item -LiteralPath $source -Destination $destination -Force
    }
}

$sensitivePatterns = @(
    ('2628' + '224058'),
    ('A856' + '966869225'),
    ('b4:8c' + ':9d:ad:3f:0b'),
    ('10.104' + '.102.178'),
    ('2d12d136' + 'af596fe'),
    ('kong' + 'xia')
)

try {
    New-Item -ItemType Directory -Path $stageDirectory -Force | Out-Null

    Copy-ProjectItem -RelativePath '.gitignore'
    Copy-ProjectItem -RelativePath 'LICENSE'
    Copy-ProjectItem -RelativePath 'README.md'
    Copy-ProjectItem -RelativePath 'Cargo.toml'
    Copy-ProjectItem -RelativePath 'Setup.cmd'
    Copy-ProjectItem -RelativePath 'htu-toolbox-cli' -Recurse
    Copy-ProjectItem -RelativePath 'htu-toolbox-lib' -Recurse
    Copy-ProjectItem -RelativePath 'scripts' -Recurse

    $webDestination = Join-Path $stageDirectory 'web'
    New-Item -ItemType Directory -Path $webDestination -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $repositoryRoot 'web\server.py') -Destination $webDestination -Force
    Copy-Item -LiteralPath (Join-Path $repositoryRoot 'web\launcher.py') -Destination $webDestination -Force
    Copy-Item -LiteralPath (Join-Path $repositoryRoot 'web\static') -Destination $webDestination -Recurse -Force

    $releaseText = @"
HTU campus network auto-login community package

Generated: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss zzz')
Runtime configuration and logs are intentionally excluded.
Run Setup.cmd to open the local dashboard, then save your account settings there to install the watcher.
"@
    [IO.File]::WriteAllText(
        (Join-Path $stageDirectory 'RELEASE.txt'),
        $releaseText,
        [Text.UTF8Encoding]::new($false)
    )

    $cacheItems = Get-ChildItem -LiteralPath $stageDirectory -Recurse -Force | Where-Object {
        $_.Name -eq '__pycache__' -or $_.Extension -eq '.pyc'
    }
    foreach ($item in $cacheItems) {
        if ($item.PSIsContainer) {
            Remove-Item -LiteralPath $item.FullName -Recurse -Force
        }
        else {
            Remove-Item -LiteralPath $item.FullName -Force
        }
    }

    $matches = foreach ($file in Get-ChildItem -LiteralPath $stageDirectory -Recurse -Force -File) {
        foreach ($pattern in $sensitivePatterns) {
            if (Select-String -LiteralPath $file.FullName -SimpleMatch -Pattern $pattern -Quiet) {
                [pscustomobject]@{
                    Pattern = $pattern
                    File    = $file.FullName.Substring($stageDirectory.Length + 1)
                }
            }
        }
    }
    if ($matches) {
        $details = $matches | ForEach-Object { "$($_.Pattern) -> $($_.File)" }
        throw "Sensitive data check failed:`n$($details -join "`n")"
    }

    if (Test-Path -LiteralPath $outputFullPath) {
        Remove-Item -LiteralPath $outputFullPath -Force
    }

    $itemsToCompress = Get-ChildItem -LiteralPath $stageDirectory -Force | Select-Object -ExpandProperty FullName
    Compress-Archive -LiteralPath $itemsToCompress -DestinationPath $outputFullPath -CompressionLevel Optimal

    $hash = Get-FileHash -LiteralPath $outputFullPath -Algorithm SHA256
    $hashPath = "$outputFullPath.sha256"
    [IO.File]::WriteAllText(
        $hashPath,
        "$($hash.Hash.ToLowerInvariant())  $([IO.Path]::GetFileName($outputFullPath))`r`n",
        [Text.UTF8Encoding]::new($false)
    )

    Write-Host "Package created: $outputFullPath"
    Write-Host "SHA256: $($hash.Hash.ToLowerInvariant())"
}
finally {
    $resolvedStage = [IO.Path]::GetFullPath($stageDirectory)
    $stageLeaf = Split-Path -Leaf $resolvedStage
    if ($resolvedStage.StartsWith($tempRoot, [StringComparison]::OrdinalIgnoreCase) -and
        $stageLeaf -like 'htu-toolbox-release-*' -and
        (Test-Path -LiteralPath $resolvedStage)) {
        Remove-Item -LiteralPath $resolvedStage -Recurse -Force
    }
}

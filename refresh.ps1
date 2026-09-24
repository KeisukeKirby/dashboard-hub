# Daily refresh of the dashboard hub, run by a Windows scheduled task.
#
# Rebuilds index.html so newly deployed dashboards appear on their own, takes a
# thumbnail for any card that has none, and pushes the generated files so Vercel
# redeploys. It touches nothing else: if the repo is not on main, or has edits
# waiting, it logs that and stops, so it can never interrupt work in progress.

$ErrorActionPreference = "Stop"
$repo = $PSScriptRoot
Set-Location $repo
$log = Join-Path $repo "refresh.log"
$generated = @("index.html", "artifact.html")

function Log($message) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm') $message"
    Add-Content -Path $log -Value $line
    Write-Output $line
}

try {
    $branch = (git rev-parse --abbrev-ref HEAD).Trim()
    if ($branch -ne "main") { Log "skip: branch is $branch, not main"; exit 0 }

    $pending = git status --porcelain | Where-Object {
        $path = $_.Substring(3)
        -not ($generated -contains $path -or $path -like "thumbs/*" -or $path -like "p/*")
    }
    if ($pending) { Log "skip: uncommitted changes ($($pending.Count) files)"; exit 0 }

    git fetch --quiet origin
    git merge --ff-only --quiet origin/main

    $out = & python build.py --shots-new 2>&1
    $out | ForEach-Object { Log "build: $_" }
    if ($LASTEXITCODE -ne 0) { Log "build failed"; exit 1 }

    git add index.html artifact.html thumbs p
    if (-not (git diff --cached --name-only)) { Log "no change"; exit 0 }

    $changed = (git diff --cached --name-only) -join ", "
    git commit --quiet -m "Refresh the hub: new dashboards, current status" -m "Automated daily run (refresh.ps1). Generated files only." -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
    git push --quiet origin main
    Log "pushed: $changed"
} catch {
    Log "error: $_"
    exit 1
}

param(
    [switch]$DryRun,
    [switch]$Continuous
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$LogDir = Join-Path $ProjectRoot "outputs\daily_research\telegram_logs"
$LogPath = Join-Path $LogDir ("telegram_bot_{0}.log" -f (Get-Date -Format "yyyy-MM-dd"))

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
Set-Location $ProjectRoot

$Token = [Environment]::GetEnvironmentVariable("TELEGRAM_BOT_TOKEN", "User")
$ChatId = [Environment]::GetEnvironmentVariable("TELEGRAM_CHAT_ID", "User")
if (-not $Token) {
    $Token = $env:TELEGRAM_BOT_TOKEN
}
if (-not $ChatId) {
    $ChatId = $env:TELEGRAM_CHAT_ID
}

$env:TELEGRAM_BOT_TOKEN = $Token
$env:TELEGRAM_CHAT_ID = $ChatId

$Python = (Get-Command python -ErrorAction Stop).Source
$Args = @("-m", "tools.daily_research.telegram_digest_bot")
if (-not $Continuous) {
    $Args += "--once"
}
if ($DryRun) {
    $Args += "--dry-run"
}

"[{0}] Starting Telegram digest bot. DryRun={1} Continuous={2}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $DryRun, $Continuous | Out-File -FilePath $LogPath -Append -Encoding utf8
& $Python @Args *>> $LogPath
$ExitCode = $LASTEXITCODE
"[{0}] Finished Telegram digest bot. ExitCode={1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $ExitCode | Out-File -FilePath $LogPath -Append -Encoding utf8

exit $ExitCode

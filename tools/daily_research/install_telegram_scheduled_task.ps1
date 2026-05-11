param(
    [string]$TaskName = "DailyResearchTelegramBot",
    [int]$IntervalMinutes = 30,
    [string]$TelegramBotToken = "",
    [string]$TelegramChatId = "",
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

if (-not $TelegramBotToken) {
    $TelegramBotToken = [Environment]::GetEnvironmentVariable("TELEGRAM_BOT_TOKEN", "User")
}
if (-not $TelegramBotToken) {
    $SecureToken = Read-Host "Telegram bot token" -AsSecureString
    $TokenPtr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecureToken)
    try {
        $TelegramBotToken = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($TokenPtr)
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($TokenPtr)
    }
}

if (-not $TelegramChatId) {
    $TelegramChatId = [Environment]::GetEnvironmentVariable("TELEGRAM_CHAT_ID", "User")
}
if (-not $TelegramChatId) {
    $TelegramChatId = Read-Host "Telegram chat id"
}

[Environment]::SetEnvironmentVariable("TELEGRAM_BOT_TOKEN", $TelegramBotToken, "User")
[Environment]::SetEnvironmentVariable("TELEGRAM_CHAT_ID", $TelegramChatId, "User")

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Runner = Join-Path $PSScriptRoot "run_telegram_digest_bot.ps1"
$PowerShell = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$RunnerArgs = "-NoProfile -ExecutionPolicy Bypass -File `"$Runner`""
if ($DryRun) {
    $RunnerArgs += " -DryRun"
}

$Action = New-ScheduledTaskAction `
    -Execute $PowerShell `
    -Argument $RunnerArgs `
    -WorkingDirectory $ProjectRoot

$Trigger = New-ScheduledTaskTrigger `
    -Once `
    -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes) `
    -RepetitionDuration (New-TimeSpan -Days 3650)

$Settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes ([Math]::Max($IntervalMinutes - 1, 20)))

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Description "Runs the DeFi/Core daily research Telegram digest bot every $IntervalMinutes minutes." `
    -Force | Out-Null

Write-Host "Installed scheduled task: $TaskName"
Write-Host "Interval: every $IntervalMinutes minutes"
Write-Host "Runner: $Runner"
Write-Host "Logs: $ProjectRoot\outputs\daily_research\telegram_logs"
Write-Host ""
Write-Host "To test immediately:"
Write-Host "  Start-ScheduledTask -TaskName `"$TaskName`""

param(
    [string]$TaskName = "DailyResearchTelegramBot",
    [int]$IntervalMinutes = 30,
    [string]$TelegramBotToken = "",
    [string]$TelegramChatId = "",
    [switch]$Continuous
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
$HiddenRunner = Join-Path $PSScriptRoot "run_telegram_digest_bot_hidden.vbs"
$WScript = "$env:SystemRoot\System32\wscript.exe"
$RunnerArgument = "`"$HiddenRunner`""
if ($Continuous) {
    $RunnerArgument = "$RunnerArgument -Continuous"
}

$Action = New-ScheduledTaskAction `
    -Execute $WScript `
    -Argument $RunnerArgument `
    -WorkingDirectory $ProjectRoot

if ($Continuous) {
    $Trigger = New-ScheduledTaskTrigger -AtLogOn
    $Settings = New-ScheduledTaskSettingsSet `
        -StartWhenAvailable `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -MultipleInstances IgnoreNew `
        -ExecutionTimeLimit (New-TimeSpan -Days 3650)
    $Description = "Runs the DeFi/Core daily research Telegram digest bot continuously in the background. Collection interval is controlled by the config file."
}
else {
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
    $Description = "Runs the DeFi/Core daily research Telegram digest bot every $IntervalMinutes minutes without showing a console window."
}

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Description $Description `
    -Force | Out-Null

Write-Host "Installed hidden scheduled task: $TaskName"
if ($Continuous) {
    Write-Host "Mode: continuous background listener"
    Write-Host "Collection interval comes from tools\daily_research\config\telegram_bot.config.example.json"
}
else {
    Write-Host "Mode: scheduled --once runner"
    Write-Host "Interval: every $IntervalMinutes minutes"
}
Write-Host "Runner: $HiddenRunner"
Write-Host "Logs: $ProjectRoot\outputs\daily_research\telegram_logs"

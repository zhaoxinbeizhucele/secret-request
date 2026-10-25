param(
    [string]$Python = 'python',
    [string]$ApplicationDirectory,
    [switch]$BuildNotifier,
    [ValidateSet('public','custom')][string]$Mode,
    [string]$Url,
    [string]$ConfigDirectory,
    [switch]$LocalNotification,
    [switch]$NoLocalNotification,
    [switch]$ConfigureWecom,
    [string]$WebhookEnv,
    [ValidateSet('wecom','generic')][string]$WebhookType = 'wecom'
)
$ErrorActionPreference = 'Stop'
$taskArguments = @('-I', (Join-Path $PSScriptRoot 'install.py'))
if ($ApplicationDirectory) { $taskArguments += @('--application-directory', $ApplicationDirectory) }
if ($BuildNotifier) { $taskArguments += '--build-notifier' }
if ($Mode) { $taskArguments += @('--mode', $Mode) }
if ($Url) { $taskArguments += @('--url', $Url) }
if ($ConfigDirectory) { $taskArguments += @('--config-directory', $ConfigDirectory) }
if ($NoLocalNotification) { $taskArguments += '--no-local-notification' }
if ($LocalNotification) { $taskArguments += '--local-notification' }
if ($ConfigureWecom) { $taskArguments += '--configure-wecom' }
if ($WebhookEnv) { $taskArguments += @('--webhook-env', $WebhookEnv, '--webhook-type', $WebhookType) }
& $Python @taskArguments
if ($LASTEXITCODE -ne 0) { throw 'Client installation failed.' }

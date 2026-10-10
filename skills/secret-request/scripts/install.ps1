param([string]$Python = 'python', [string]$ApplicationDirectory, [switch]$BuildNotifier, [string]$Url, [string]$ConfigDirectory, [switch]$NoLocalNotification, [string]$WebhookEnv, [ValidateSet('wecom','generic')][string]$WebhookType = 'wecom')
$ErrorActionPreference = 'Stop'
$taskArguments = @('-I', (Join-Path $PSScriptRoot 'install.py'))
if ($ApplicationDirectory) { $taskArguments += @('--application-directory', $ApplicationDirectory) }
if ($BuildNotifier) { $taskArguments += '--build-notifier' }
if ($Url) { $taskArguments += @('--url', $Url) }
if ($ConfigDirectory) { $taskArguments += @('--config-directory', $ConfigDirectory) }
if ($NoLocalNotification) { $taskArguments += '--no-local-notification' }
if ($WebhookEnv) { $taskArguments += @('--webhook-env', $WebhookEnv, '--webhook-type', $WebhookType) }
& $Python @taskArguments
if ($LASTEXITCODE -ne 0) { throw 'Client installation failed.' }

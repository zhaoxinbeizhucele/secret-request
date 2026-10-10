param([string]$Python = 'python', [string]$ApplicationDirectory, [switch]$BuildNotifier, [string]$ConfigFile, [string]$ConfigDirectory)
$ErrorActionPreference = 'Stop'
$taskArguments = @('-I', (Join-Path $PSScriptRoot 'install.py'))
if ($ApplicationDirectory) { $taskArguments += @('--application-directory', $ApplicationDirectory) }
if ($BuildNotifier) { $taskArguments += '--build-notifier' }
if ($ConfigFile) { $taskArguments += @('--config-file', $ConfigFile) }
if ($ConfigDirectory) { $taskArguments += @('--config-directory', $ConfigDirectory) }
& $Python @taskArguments
if ($LASTEXITCODE -ne 0) { throw 'Client installation failed.' }

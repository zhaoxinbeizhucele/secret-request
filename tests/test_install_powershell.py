"""The Windows convenience entry forwards the same mode and setup options."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest

POWERSHELL = shutil.which('pwsh') or shutil.which('powershell')
WRAPPER = Path(__file__).resolve().parents[1]/'skills/secret-request/scripts/install.ps1'


@pytest.mark.skipif(not POWERSHELL, reason='PowerShell is not installed')
@pytest.mark.parametrize(('options','expected'),[
    ('-Mode public -ConfigureWecom -ConfigDirectory "configuration with spaces"',
     ['--mode','public','--config-directory','configuration with spaces','--configure-wecom']),
    ('-Mode custom -Url https://custom.example -WebhookEnv TEST_HOOK -NoLocalNotification',
     ['--mode','custom','--url','https://custom.example','--no-local-notification','--webhook-env','TEST_HOOK','--webhook-type','wecom'])])
def test_wrapper_forwards_arguments_without_running_installer(tmp_path,options,expected):
    script = tmp_path/'invoke.ps1'
    literal = str(WRAPPER).replace("'","''")
    script.write_text("function Test-Python { $global:LASTEXITCODE = 0; ConvertTo-Json -InputObject @($args) -Compress }\n"+
                      "& '"+literal+"' -Python Test-Python "+options+"\n",encoding='utf-8')
    result = subprocess.run([POWERSHELL,'-NoProfile','-NonInteractive','-File',str(script)],capture_output=True,timeout=15)
    assert result.returncode == 0,result.stderr.decode(errors='replace')
    assert json.loads(result.stdout.decode('utf-8-sig')) == ['-I',str(WRAPPER.parent/'install.py'),*expected]

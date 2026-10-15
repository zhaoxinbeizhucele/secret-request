"""The distributed skill must execute its own modules outside the checkout."""
import json
from pathlib import Path
import shutil
import subprocess
import sys

from secret_request.session import read_message, write_message

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "skills/secret-request"


def test_client_bundle_matches_source():
    # Prevent publishing stale copies after a client change.
    for name in ("__init__.py", "client.py", "crypto.py", "fields.py", "notifications.py", "session.py", "windows_job.py", "relay.py", "server.py"):
        assert (BUNDLE / "scripts/secret_request" / name).read_bytes() == (ROOT / "secret_request" / name).read_bytes()
    for name in ('index.html', 'app.js', 'crypto.js', 'style.css', 'home.html', 'home.css', 'home.js'):
        assert (BUNDLE/'scripts/secret_request/web'/name).read_bytes() == (ROOT/'secret_request/web'/name).read_bytes()


def test_copied_skill_runs_outside_checkout(tmp_path):
    installed = tmp_path / "copied skill"
    shutil.copytree(BUNDLE, installed, ignore=shutil.ignore_patterns("__pycache__"))
    scripts = installed / "scripts"
    entry = scripts / "secret_request_cli.py"
    # Hostile/unrelated cwd package must not shadow the bundled client or broker.
    cwd = tmp_path / "working directory"
    (cwd / "secret_request").mkdir(parents=True)
    (cwd / "secret_request/__init__.py").write_text("raise RuntimeError('wrong package')")
    def cli(*arguments):
        return subprocess.run([sys.executable, "-I", "-X", "utf8", str(entry), *arguments],
                              cwd=cwd, capture_output=True, text=True, encoding="utf-8", timeout=15)
    assert cli("--help").returncode == 0
    # Keep the broker's empty OS-lock files in this test's profile, not the real user's.
    code = ("import runpy,sys; from pathlib import Path; "
            "test_profile=Path(sys.argv.pop(2)); Path.home=lambda:test_profile; "
            "sys.path.insert(0,sys.argv.pop(1)); "
            "runpy.run_module('secret_request.session',run_name='__main__')")
    created = subprocess.Popen([sys.executable,"-I","-X","utf8","-c",code,
                                str(scripts),str(tmp_path/'test profile')],
                               cwd=cwd,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
    write_message(created.stdin, {'secret':'FAKE-BUNDLED','env':'REQUEST_TEST_SECRET',
                                 'ttl':30,'cwd':str(cwd)})
    created.stdin.close()
    handle = read_message(created.stdout)["session"]
    created.stdout.close()
    try:
        result = cli("--use-session", handle, "--", sys.executable, "-c",
                     "import os; assert os.environ['REQUEST_TEST_SECRET']=='FAKE-BUNDLED'")
        assert result.returncode == 0, result.stdout
        assert "FAKE-BUNDLED" not in result.stdout + result.stderr
        state = cli("--session-status", handle)
        assert json.loads(state.stdout)["last_result"]["exit_code"] == 0
    finally:
        assert cli("--revoke-session", handle).returncode == 0
        created.wait(timeout=10)

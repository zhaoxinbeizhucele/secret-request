import json
from pathlib import Path
import subprocess
import pytest
from secret_request.crypto import public_jwk, decrypt

@pytest.mark.parametrize("value", [" FAKE-unicode🔒  ", "first\nsecond\n", "x"*65536], ids=["unicode", "multiline", "maximum"])
def test_browser_webcrypto_compatible_with_python(key, value):
    module=(Path(__file__).resolve().parents[1]/"secret_request/web/crypto.js").as_uri()
    script="const {readFile}=await import('node:fs/promises'); const source=await readFile(new URL(process.argv[1])); const {encryptSecret}=await import('data:text/javascript;base64,'+source.toString('base64')); let input=''; for await (const chunk of process.stdin) input+=chunk; const data=JSON.parse(input); process.stdout.write(JSON.stringify(await encryptSecret(data.value,data.key,'test-id')));"
    result=subprocess.run(["node","--input-type=module","-e",script,module],input=json.dumps({"key":public_jwk(key),"value":value}),capture_output=True,text=True,encoding="utf-8",timeout=10,check=True)
    assert value not in result.stdout
    assert decrypt(key,"test-id",json.loads(result.stdout))==value

def test_browser_crypto_rejects_oversize_and_nul(key):
    module=(Path(__file__).resolve().parents[1]/"secret_request/web/crypto.js").as_uri()
    script="const {readFile}=await import('node:fs/promises'); const source=await readFile(new URL(process.argv[1])); const {encryptSecret}=await import('data:text/javascript;base64,'+source.toString('base64')); for(const value of ['', 'x'.repeat(65537), 'a\\0b']) { let failed=false;try{await encryptSecret(value,{},'x');}catch(e){failed=e.message==='size';} if(!failed)process.exit(1); }"
    subprocess.run(["node","--input-type=module","-e",script,module],capture_output=True,timeout=10,check=True)

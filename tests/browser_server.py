"""Disposable loopback-only browser fixture. Never deploy this module."""
import secrets
import os
import json
import httpx
from secret_request.relay import Settings, create_app
from secret_request.crypto import new_key, public_jwk, decrypt

agent=secrets.token_urlsafe(32)
BASE = "http://127.0.0.1:" + os.environ.get("SECRET_REQUEST_TEST_PORT", "18787")
app=create_app(Settings(BASE, {"测试设备":{"token":agent}}, allow_local_http=True))
fixtures={}

@app.get("/test/create")
async def create(multiple: bool = False):
    key=new_key()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url=BASE) as client:
        fields = [{"id":"username","label":"用户名","type":"text"}, {"id":"password","label":"密码","type":"password"}, {"id":"key","label":"备注机密","type":"textarea","required":False}] if multiple else None
        result=(await client.post("/api/requests",headers={"Authorization":"Bearer "+agent},json={"name":"浏览器测试凭据","purpose":"仅验证 Windows 输入与加密传递；请输入 FAKE-ONLY-TEST。","agent":"测试 Agent","fields":fields,"public_key":public_jwk(key)})).json()
        entry=app.state.entries[result["id"]]
        fixtures[result["id"]]=(key,result["receive_token"])
        return {"url":result["input_url"],"id":entry.id}

@app.get("/test/check/{rid}")
async def check(rid:str):
    key,token=fixtures[rid]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url=BASE) as client:
        response=await client.post(f"/api/requests/{rid}/consume",headers={"Authorization":"Bearer "+token},json={})
        if response.status_code!=200:return {"state":app.state.entries[rid].state,"matches":False}
        value=decrypt(key,rid,response.json()["envelope"])
        expected = {"username":" FAKE-用户 ","password":"FAKE-ONLY-TEST","key":"line1\nline2\n"}
        matches = json.loads(value) == expected if app.state.entries[rid].fields else value in {"FAKE-ONLY-TEST", "FAKE-ONLY-TEST\nsecond line"}
        return {"state":"consumed","matches":matches}

@app.get("/test/cancel/{rid}")
async def cancel(rid:str):
    key,token=fixtures[rid]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url=BASE) as client:
        return (await client.post(f"/api/requests/{rid}/cancel",headers={"Authorization":"Bearer "+token},json={})).json()

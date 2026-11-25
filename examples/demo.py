"""Run a disposable two-member ContextMesh demo using the official MCP client."""
import asyncio
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def running(db):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    url = f"http://127.0.0.1:{port}/mcp"
    p = subprocess.Popen([sys.executable, str(ROOT / "contextmesh.py"), "--db", str(db),
                          "serve", "--port", str(port)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        with httpx.Client(trust_env=False) as client:
            for _ in range(100):
                if p.poll() is not None:
                    raise RuntimeError("MCP service exited during startup")
                try:
                    if client.get(url).status_code == 401:
                        break
                except httpx.ConnectError:
                    pass
                time.sleep(0.05)
            else:
                raise RuntimeError("Service failed to start")
        yield url
    finally:
        p.terminate()
        p.wait(timeout=10)


@asynccontextmanager
async def session(url, key):
    async with httpx.AsyncClient(headers={"Authorization": "Bearer " + key}, trust_env=False) as http:
        async with streamable_http_client(url, http_client=http) as (read, write, _):
            async with ClientSession(read, write) as client:
                await client.initialize()
                yield client


async def call(client, tool, **params):
    reply = await client.call_tool(tool, params)
    if reply.isError:
        raise ValueError(reply.content[0].text)
    payload = reply.structuredContent
    return payload["result"] if set(payload) == {"result"} else payload



def issue(db, project, person):
    return subprocess.check_output([sys.executable, str(ROOT / "contextmesh.py"), "--db", str(db),
                                    "grant", project, person], text=True).strip()


async def demo():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "demo.sqlite3"
        alice, bob = issue(db, "login", "Alice"), issue(db, "login", "Bob")
        with running(db) as url:
            async with session(url, alice) as publisher:
                original = await call(publisher, "publish_context", topic="登录验证", audiences=["企业试点", "公众注册"],
                                      decision="使用短信验证码", source="演示：初版评审")
                print(f"Alice 发布初版：{original['id']}，两组用户均使用短信。")
                update = await call(publisher, "publish_context", topic="登录验证", audiences=["企业试点"],
                                    decision="使用邮箱验证码", source="演示：企业试用反馈", replaces=original["id"])
                print(f"Alice 更新试点条款：{update['id']}。")
            async with session(url, bob) as reviewer:
                for audience, case in [("企业试点", "T-17"), ("公众注册", "T-18")]:
                    result = await call(reviewer, "check_reference", id=original["id"], audience=audience)
                    current = result["current"]
                    print(f"Bob 核对 {case}（{audience}）：{result['status']} → {current['decision']}，{current['source']}。")


if __name__ == "__main__":
    asyncio.run(demo())

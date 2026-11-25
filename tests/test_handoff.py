"""Integration tests for the shared decision pool, over the real HTTP MCP transport."""
import asyncio
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import httpx
from examples.demo import ROOT, call, issue, running, session


class TestHandoff(unittest.IsolatedAsyncioTestCase):
    async def test_shared_pool(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "pool.sqlite3"
            cli = [sys.executable, str(ROOT / "contextmesh.py"), "--db", str(db)]
            alice, bob, outsider = issue(db, "Login", "Alice"), issue(db, "Login", "Bob"), issue(db, "Other", "Alice")
            base = dict(topic="登录", audiences=["试点", "公众"], decision="短信", source="评审 #1")
            with running(db) as url:
                async with session(url, alice) as a, session(url, bob) as b, session(url, outsider) as x:
                    first = await call(a, "publish_context", **base)
                    self.assertEqual(first["id"], (await call(a, "publish_context", **base))["id"])
                    update = dict(base, audiences=["试点"], decision="邮箱", replaces=first["id"])
                    # Two writers racing on one version: exactly one succeeds.
                    results = await asyncio.gather(call(a,"publish_context",**update),
                                                   call(b,"publish_context",**update), return_exceptions=True)
                    self.assertEqual(sum(isinstance(r,ValueError) for r in results),1)
                    second = next(r for r in results if isinstance(r,dict))
                    self.assertEqual(await call(x, "search_context"), [])
                    self.assertEqual(await call(x, "recent_context"), [])
                    self.assertEqual((await call(x, "check_reference", id=first["id"], audience="公众"))["status"], "unknown_reference")
            with running(db) as url:
                async with session(url, bob) as b, session(url, alice) as a:
                    self.assertEqual((await call(b,"search_context",query="登录",audience="试点"))[0]["decision"],"邮箱")
                    rows = await call(b,"search_context",audience="公众")
                    self.assertEqual(rows[0]["id"],first["id"])
                    for audience,status in [("公众","current"),("试点","needs_review"),("未标明","scope_mismatch")]:
                        self.assertEqual((await call(b,"check_reference",id=first["id"],audience=audience))["status"],status)
                    author, other = (a,b) if second["author"]=="Alice" else (b,a)
                    with self.assertRaises(ValueError):
                        await call(other,"withdraw_context",id=second["id"])
                    await call(author,"withdraw_context",id=second["id"])
                    self.assertEqual(await call(b,"search_context",audience="试点"),[])
                    self.assertTrue((await call(b,"recent_context"))[0]["withdrawn"])
                subprocess.run(cli+["revoke","Login","Alice"],check=True)
                with httpx.Client(trust_env=False) as http:
                    self.assertEqual(http.get(url,headers={"Authorization":"Bearer "+alice}).status_code,401)


if __name__ == "__main__":
    unittest.main()

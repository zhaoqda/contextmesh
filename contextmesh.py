"""ContextMesh: a project-scoped, persistent MCP decision pool."""
import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import secrets
import sqlite3
from typing import Any
from uuid import uuid4

import uvicorn
from mcp.server.fastmcp import Context, FastMCP
from starlette.datastructures import Headers
from starlette.responses import JSONResponse


def connect(path):
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    return db


def initialize(path):
    with closing(connect(path)) as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS members (
          project TEXT NOT NULL, name TEXT NOT NULL, digest TEXT NOT NULL UNIQUE,
          PRIMARY KEY(project, name)
        );
        CREATE TABLE IF NOT EXISTS decisions (
          id TEXT PRIMARY KEY, project TEXT NOT NULL, author TEXT NOT NULL,
          topic TEXT NOT NULL, audiences TEXT NOT NULL, decision TEXT NOT NULL,
          source TEXT NOT NULL, replaces TEXT REFERENCES decisions(id),
          created TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
          withdrawn INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS decisions_project ON decisions(project,topic);
        CREATE TABLE IF NOT EXISTS active (
          project TEXT NOT NULL, topic TEXT NOT NULL, audience TEXT NOT NULL,
          id TEXT NOT NULL REFERENCES decisions(id), PRIMARY KEY(project,topic,audience)
        );
        """)


def grant(path, project, name):
    project, name = clean(project, 120), clean(name, 120)
    token = secrets.token_urlsafe(32)
    with closing(connect(path)) as db, db:
        db.execute("INSERT OR REPLACE INTO members VALUES(?,?,?)",
                   (project, name, digest(token)))
    return token


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def clean(value, limit=4000):
    value = value.strip()
    if not 0 < len(value) <= limit:
        raise ValueError(f"Expected nonempty text of at most {limit} characters.")
    return value


def record(row):
    data = dict(row)
    data["audiences"] = json.loads(data["audiences"])
    data["withdrawn"] = bool(data["withdrawn"])
    return data


def build_app(path, host="127.0.0.1"):
    initialize(path)
    server = FastMCP("ContextMesh", host=host, stateless_http=True, json_response=True,
                     instructions="Search current decisions before project work. Publish only confirmed shared facts.")

    @server.tool()
    def publish_context(topic: str, audiences: list[str], decision: str, source: str,
                        ctx: Context, replaces: str = "") -> dict[str, Any]:
        """Publish one confirmed decision for named audiences. To revise, give their current decision ID as replaces."""
        project, author = ctx.request_context.request.state.member
        topic, decision, source = clean(topic, 200), clean(decision), clean(source)
        if not 1 <= len(audiences) <= 100:
            raise ValueError("Provide 1–100 explicit audiences.")
        groups = sorted({clean(x, 160) for x in audiences})
        with closing(connect(path)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            # Recognize a retry if this exact publication is still live in all requested scopes.
            current = {r["audience"]: r["id"] for r in db.execute(
                "SELECT audience,id FROM active WHERE project=? AND topic=?", (project, topic))}
            heads = {current.get(g) for g in groups}
            if len(heads) == 1 and None not in heads:
                row = db.execute("SELECT * FROM decisions WHERE id=?", (next(iter(heads)),)).fetchone()
                existing = record(row)
                if (existing["author"], existing["audiences"], existing["decision"],
                    existing["source"], existing["replaces"]) == (author, groups, decision, source, replaces or None):
                    return existing
            if heads != {replaces or None}:
                raise ValueError("Version conflict: search_context first; revise scopes sharing the same current ID.")
            key = str(uuid4())
            db.execute("""INSERT INTO decisions(id,project,author,topic,audiences,decision,source,replaces)
                         VALUES(?,?,?,?,?,?,?,?)""", (key, project, author, topic, json.dumps(groups), decision, source, replaces or None))
            db.executemany("INSERT OR REPLACE INTO active VALUES(?,?,?,?)",
                           [(project, topic, group, key) for group in groups])
            return record(db.execute("SELECT * FROM decisions WHERE id=?", (key,)).fetchone())

    @server.tool()
    def search_context(ctx: Context, query: str = "", audience: str = "", offset: int = 0) -> list[dict[str, Any]]:
        """Find current decisions by text and optional exact audience. Returns 50 current scope bindings per page."""
        project, _ = ctx.request_context.request.state.member
        with closing(connect(path)) as db:
            rows = db.execute("""SELECT d.*,a.audience AS active_audience FROM active a
                JOIN decisions d ON d.id=a.id WHERE a.project=? AND (?='' OR a.audience=?)
                AND instr(lower(d.topic||' '||d.decision||' '||d.source||' '||a.audience),lower(?))>0
                ORDER BY d.created DESC,d.id,a.audience LIMIT 50 OFFSET ?""",
                (project, audience.strip(), audience.strip(), query.strip(), max(0, offset)))
            return [record(row) for row in rows]

    @server.tool()
    def check_reference(id: str, audience: str, ctx: Context) -> dict[str, Any]:
        """Check whether a task's cited decision is current for its audience; return the replacement and source."""
        project, _ = ctx.request_context.request.state.member
        audience = clean(audience, 160)
        with closing(connect(path)) as db:
            db.execute("BEGIN")
            cited = db.execute("SELECT * FROM decisions WHERE id=? AND project=?", (id, project)).fetchone()
            if not cited:
                return {"status": "unknown_reference"}
            if audience not in json.loads(cited["audiences"]):
                return {"status": "scope_mismatch", "id": id, "audience": audience}
            head = db.execute("""SELECT d.* FROM active a JOIN decisions d ON a.id=d.id
                               WHERE a.project=? AND a.topic=? AND a.audience=?""",
                              (project, cited["topic"], audience)).fetchone()
            return {"status": ("current" if head["id"] == id else "needs_review") if head else "no_current_rule",
                    "cited_id": id, "audience": audience, "current": record(head) if head else None}

    @server.tool()
    def recent_context(ctx: Context, offset: int = 0) -> list[dict[str, Any]]:
        """List publications newest first, including replaced and withdrawn records, with currently active audiences."""
        project, _ = ctx.request_context.request.state.member
        with closing(connect(path)) as db:
            db.execute("BEGIN")
            result = []
            for row in db.execute("SELECT * FROM decisions WHERE project=? ORDER BY rowid DESC LIMIT 50 OFFSET ?",
                                  (project, max(0, offset))):
                data = record(row)
                data["active_audiences"] = [r[0] for r in db.execute(
                    "SELECT audience FROM active WHERE id=? ORDER BY audience", (data["id"],))]
                result.append(data)
            return result

    @server.tool()
    def withdraw_context(id: str, ctx: Context) -> dict[str, Any]:
        """Withdraw one's own publication from current results. Historical metadata is retained; older rules do not revive."""
        project, author = ctx.request_context.request.state.member
        with closing(connect(path)) as db, db:
            found = db.execute("UPDATE decisions SET withdrawn=1 WHERE id=? AND project=? AND author=?",
                               (id, project, author))
            if not found.rowcount:
                raise ValueError("No withdrawable publication for this identity.")
            db.execute("DELETE FROM active WHERE id=?", (id,))
        return {"id": id, "withdrawn": True}

    app = server.streamable_http_app()

    async def authenticated(scope, receive, send):
        if scope["type"] == "http":
            scheme, _, token = Headers(scope=scope).get("authorization", "").partition(" ")
            with closing(connect(path)) as db:
                member = db.execute("SELECT project,name FROM members WHERE digest=?", (digest(token),)).fetchone()
            if scheme.lower() != "bearer" or not member:
                await JSONResponse({"error": "Invalid project member token"}, status_code=401,
                                   headers={"WWW-Authenticate": "Bearer"})(scope, receive, send)
                return
            scope.setdefault("state", {})["member"] = tuple(member)
        await app(scope, receive, send)
    return authenticated


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path("contextmesh.sqlite3"))
    commands = parser.add_subparsers(dest="command", required=True)
    member = commands.add_parser("grant", help="Create or rotate a member token; stdout is the token.")
    member.add_argument("project")
    member.add_argument("name")
    revoke = commands.add_parser("revoke")
    revoke.add_argument("project")
    revoke.add_argument("name")
    serve = commands.add_parser("serve")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()
    if args.command == "serve":
        uvicorn.run(build_app(args.db, args.host), host=args.host, port=args.port)
    else:
        initialize(args.db)
        if args.command == "grant":
            print(grant(args.db, args.project, args.name))
        else:
            with closing(connect(args.db)) as db, db:
                db.execute("DELETE FROM members WHERE project=? AND name=?", (args.project, args.name))


if __name__ == "__main__":
    main()

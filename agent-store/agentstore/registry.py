"""注册表：版本一旦发布就不可覆盖（可撤销，不可改），这是应用商店的信任底线。"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from .manifest import AgentManifest, bump

SCHEMA = """
CREATE TABLE IF NOT EXISTS agents (
    agent_id   TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    developer  TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS versions (
    agent_id   TEXT NOT NULL,
    version    TEXT NOT NULL,
    developer  TEXT NOT NULL,        -- 发布者：决定谁能继续往上发版本
    digest     TEXT NOT NULL,
    manifest   TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'published',  -- published | yanked
    created_at TEXT NOT NULL,
    PRIMARY KEY (agent_id, version)
);
CREATE TABLE IF NOT EXISTS installs (
    buyer      TEXT NOT NULL,
    agent_id   TEXT NOT NULL,
    version    TEXT NOT NULL,
    granted    TEXT NOT NULL,      -- 逗号分隔的已授权权限
    installed_at TEXT NOT NULL,
    PRIMARY KEY (buyer, agent_id)
);
"""


class RegistryError(ValueError):
    pass


@dataclass
class Version:
    agent_id: str
    version: str
    digest: str
    manifest: AgentManifest
    status: str
    created_at: str
    developer: str = ""


class Registry:
    def __init__(self, db_path: str = ":memory:", now: str = "2026-11-12T00:00:00Z"):
        self.conn = sqlite3.connect(db_path)
        self.conn.executescript(SCHEMA)
        self._now = now

    # ---- 发布 ----------------------------------------------------
    def publish(self, m: AgentManifest, developer: str) -> Version:
        m.validate()
        cur = self.conn.execute("SELECT digest FROM versions WHERE agent_id=? AND version=?",
                                (m.agent_id, m.version))
        row = cur.fetchone()
        if row:
            raise RegistryError(
                f"{m.agent_id}@{m.version} 已发布（digest={row[0][:12]}）；改内容必须发新版本号")
        # agent_id 一旦被某个开发者占用，别人就不能往上发版本。
        # 原先 versions 不记 developer、也不校验归属：任何账号发一个 9.9.9
        # 就能成为「最新版」，买家装到攻击者声明的全套权限（含 payment.charge）。
        owner = self.conn.execute("SELECT developer FROM agents WHERE agent_id=?",
                                  (m.agent_id,)).fetchone()
        if owner and owner[0] != developer:
            raise RegistryError(
                f"{m.agent_id} 属于 {owner[0]}，{developer} 不能发布它的版本（首次发布即确立归属）")
        self.conn.execute(
            "INSERT OR IGNORE INTO agents(agent_id,name,developer,created_at) VALUES(?,?,?,?)",
            (m.agent_id, m.name, developer, self._now))
        self.conn.execute(
            "INSERT INTO versions(agent_id,version,developer,digest,manifest,status,created_at) "
            "VALUES(?,?,?,?,?, 'published', ?)",
            (m.agent_id, m.version, developer, m.digest(), _dump(m), self._now))
        self.conn.commit()
        return Version(m.agent_id, m.version, m.digest(), m, "published", self._now, developer)

    def yank(self, agent_id: str, version: str) -> None:
        """下架不回删：买家已有安装仍可用（或按策略停服），但不能新装。"""
        n = self.conn.execute("UPDATE versions SET status='yanked' WHERE agent_id=? AND version=?",
                              (agent_id, version)).rowcount
        if not n:
            raise RegistryError(f"没有这个版本: {agent_id}@{version}")
        self.conn.commit()

    # ---- 查询 ----------------------------------------------------
    def get(self, agent_id: str, version: str) -> Version:
        row = self.conn.execute(
            "SELECT digest,manifest,status,created_at,developer FROM versions "
            "WHERE agent_id=? AND version=?",
            (agent_id, version)).fetchone()
        if not row:
            raise RegistryError(f"没有这个版本: {agent_id}@{version}")
        return Version(agent_id, version, row[0], _load(row[1]), row[2], row[3], row[4])

    def latest(self, agent_id: str, include_yanked: bool = False) -> Version:
        rows = self.conn.execute(
            "SELECT version,digest,manifest,status,created_at,developer FROM versions WHERE agent_id=?",
            (agent_id,)).fetchall()
        if not rows:
            raise RegistryError(f"没有这个 agent: {agent_id}")
        if not include_yanked:
            rows = [r for r in rows if r[3] == "published"]
        if not rows:
            raise RegistryError(f"{agent_id} 的所有版本都已下架")
        from .manifest import parse_version
        rows.sort(key=lambda r: parse_version(r[0]))
        v, d, mf, st, at, dev = rows[-1]
        return Version(agent_id, v, d, _load(mf), st, at, dev)

    def install(self, buyer: str, agent_id: str, granted: tuple[str, ...] | None = None) -> Version:
        v = self.latest(agent_id)
        # 摘要的唯一用途就是在正文被动过时说话（npm integrity / sigstore 的同一立场）：
        # 版本表同时存 digest 与 manifest，只读 manifest 不复核，等于摘要从不生效。
        actual = v.manifest.digest()
        if actual != v.digest:
            raise RegistryError(
                f"{agent_id}@{v.version} 清单内容与发布摘要不符"
                f"（发布 {v.digest[:12]}，当前 {actual[:12]}）；拒绝安装")
        perm = v.manifest.permissions
        granted = tuple(granted if granted is not None else perm)
        extra = [g for g in granted if g not in perm]
        if extra:
            raise RegistryError(f"授权了清单里没有的权限: {extra}")
        self.conn.execute(
            "INSERT INTO installs(buyer,agent_id,version,granted,installed_at) VALUES(?,?,?,?,?) "
            "ON CONFLICT(buyer,agent_id) DO UPDATE SET version=excluded.version, granted=excluded.granted",
            (buyer, agent_id, v.version, ",".join(sorted(granted)), self._now))
        self.conn.commit()
        return v

    def granted(self, buyer: str, agent_id: str) -> tuple[str, ...]:
        row = self.conn.execute("SELECT granted FROM installs WHERE buyer=? AND agent_id=?",
                                (buyer, agent_id)).fetchone()
        if not row:
            raise RegistryError(f"{buyer} 未安装 {agent_id}")
        return tuple(p for p in row[0].split(",") if p)

    def require_upgrade(self, agent_id: str, part: str = "patch") -> str:
        return bump(self.latest(agent_id).version, part)


def _dump(m: AgentManifest) -> str:
    import json
    return json.dumps(m.canonical(), ensure_ascii=False)


def _load(s: str) -> AgentManifest:
    import json
    from .manifest import Pricing
    d = json.loads(s)
    d["permissions"] = tuple(d["permissions"])
    d["needs"] = tuple(d.get("needs") or ())
    d["pricing"] = Pricing(**d["pricing"])
    return AgentManifest(**d)

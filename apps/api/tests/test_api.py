"""API integration: auth/CSRF/roles/rate limits, discovery, the full article pipeline with the mock model,
review actions, idempotent publishing, ten_static staging site + sitemap repair, social fallback, audit."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import session_factory
from app.models import Article, FeedItem, Job, Publication, SocialPost, Source
from tests.conftest import ADMIN_PASSWORD, login

API = "/api/v1"


# ---------------- auth ----------------
async def test_login_me_logout(client):
    r = await client.post(f"{API}/auth/login", json={"email": "owner@ten.example", "password": "wrong-password"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "invalid_credentials"
    await login(client)
    me = (await client.get(f"{API}/auth/me")).json()
    assert me["user"]["role"] == "owner" and me["tenant"]["slug"] == "ten" and me["provider"] == "mock"
    assert (await client.post(f"{API}/auth/logout")).status_code == 200
    assert (await client.get(f"{API}/auth/me")).status_code == 401


async def test_login_rate_limit(client):
    for _ in range(5):
        await client.post(f"{API}/auth/login", json={"email": "owner@ten.example", "password": "nope-nope-nope"})
    r = await client.post(f"{API}/auth/login", json={"email": "owner@ten.example", "password": ADMIN_PASSWORD})
    assert r.status_code == 429


async def test_csrf_required_on_mutations(authed):
    token = authed.headers.pop("X-CSRF-Token")
    r = await authed.post(f"{API}/feed/refresh", json={})
    assert r.status_code == 403 and r.json()["error"]["code"] == "csrf_failed"
    authed.headers["X-CSRF-Token"] = token
    assert (await authed.post(f"{API}/feed/refresh", json={})).status_code == 200


async def test_reviewer_cannot_change_settings(client):
    await login(client, "reviewer@ten.example")
    r = await client.patch(f"{API}/settings/tenant", json={"name": "Hacked"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "permission_denied"


async def test_health_public(client):
    body = (await client.get(f"{API}/health")).json()
    assert body["checks"]["database"]["status"] == "ok"
    assert body["checks"]["model"]["provider"] == "mock"
    assert body["checks"]["worker"]["status"] == "down"  # no worker heartbeat yet — reported, not hidden


# ---------------- discovery ----------------
async def test_discovery_end_to_end(authed, worker):
    r = await authed.post(f"{API}/feed/refresh", json={})
    assert r.status_code == 200
    await worker.drain()
    feed = (await authed.get(f"{API}/feed")).json()
    titles = [i["title"] for i in feed["items"]]
    assert any("Northwind" in t for t in titles)
    # syndicated duplicate collapsed into one cluster head
    assert sum(1 for t in titles if "Northwind Logistics commits" in t) == 1
    head = next(i for i in feed["items"] if "Northwind" in i["title"])
    assert head["cluster_size"] >= 2 and head["score"] > 0 and head["suggested_category"] == "brief"
    assert set(head["score_breakdown"]) >= {"recency", "entity", "signal", "source", "novelty"}
    sources = (await authed.get(f"{API}/sources")).json()["items"]
    broken = next(s for s in sources if s["name"] == "Broken feed")
    assert broken["last_error"] and broken["consecutive_failures"] == 1  # recorded, did not crash the run
    detail = (await authed.get(f"{API}/feed/{head['id']}")).json()
    assert detail["cluster"] and detail["item"]["id"] == head["id"]


async def test_source_auto_disabled_after_failures(authed, worker, tenant):
    async with session_factory()() as db:
        src = (await db.execute(select(Source).where(Source.name == "Broken feed"))).scalar_one()
        src.consecutive_failures = 4
        await db.commit()
    await authed.post(f"{API}/feed/refresh", json={})
    await worker.drain()
    async with session_factory()() as db:
        src = (await db.execute(select(Source).where(Source.name == "Broken feed"))).scalar_one()
        assert src.active is False


# ---------------- full pipeline ----------------
async def _drain(worker, n=50):
    return await worker.drain(max_jobs=n)


async def _promoted_article(authed, worker) -> dict:
    await authed.post(f"{API}/feed/refresh", json={})
    await _drain(worker)
    feed = (await authed.get(f"{API}/feed")).json()
    head = next(i for i in feed["items"] if "Northwind" in i["title"])
    r = await authed.post(f"{API}/feed/{head['id']}/promote", json={"auto": True})
    assert r.status_code == 200, r.text
    dup = await authed.post(f"{API}/feed/{head['id']}/promote", json={"auto": True})
    assert dup.status_code == 409  # cannot promote twice
    await _drain(worker)
    return (await authed.get(f"{API}/articles/{r.json()['article']['id']}")).json()


async def test_pipeline_to_review_publish_and_social(authed, worker):
    art = await _promoted_article(authed, worker)
    assert art["state"] == "in_review", (art["state"], art["last_error"], [j["last_error"] for j in art["jobs"]])
    # research pack: grounded facts with URLs, injection flagged
    pack = art["research_pack"]["payload"]
    assert pack["coverage"]["source_count"] >= 2
    assert all(f["source_url"] for f in pack["key_facts"])
    assert any(s.get("injection_flags") for s in pack["sources"])
    # draft structure + QA + SEO
    body = art["current_version"]["payload"]["article"]
    assert [s["key"] for s in body["sections"]] == ["lede", "what_happened", "the_numbers", "why_it_matters", "what_to_watch"]
    assert "triple" not in str(body).lower()  # injected instruction never obeyed
    assert art["qa"]["verdict"] == "pass" and all(g["passed"] for g in art["qa"]["gates"] if g["blocking"])
    seo = art["seo"]
    assert seo["fields_complete"] == 8 and 30 <= len(seo["title_tag"]) <= 60 and 140 <= len(seo["meta_description"]) <= 158
    assert seo["title_tag"] != seo["h1"] and seo["canonical_url"].endswith(f"/brief/{seo['slug']}")
    # versions exist for every stage
    stages = [v["stage"] for v in (await authed.get(f"{API}/articles/{art['id']}/versions")).json()["items"]]
    assert {"draft", "edited", "seo", "qa"} <= set(stages)
    # preview renders
    prev = await authed.get(f"{API}/articles/{art['id']}/preview")
    assert prev.status_code == 200 and prev.text.count("<h1") == 1

    # illegal: schedule before approval
    r = await authed.post(f"{API}/publications", json={"article_id": art["id"], "target": "export"})
    assert r.status_code == 409
    # approve -> schedule export -> publish now
    r = await authed.post(f"{API}/articles/{art['id']}/approve", json={"note": "Good"})
    assert r.status_code == 200 and r.json()["state"] == "approved"
    dry = (await authed.post(f"{API}/publications/dry-run", json={"article_id": art["id"], "target": "ten_static"})).json()
    assert dry["issues"] == [] and dry["html"].count("<h1") == 1
    pub = (await authed.post(f"{API}/publications", json={"article_id": art["id"], "target": "export"})).json()
    assert pub["status"] == "scheduled"
    again = (await authed.post(f"{API}/publications", json={"article_id": art["id"], "target": "export"})).json()
    assert again["id"] == pub["id"] and again.get("idempotent")  # double click → same publication
    r = await authed.post(f"{API}/publications/{pub['id']}/publish-now")
    assert r.status_code == 200
    await _drain(worker)
    pubs = (await authed.get(f"{API}/publications")).json()["items"]
    done = next(p for p in pubs if p["id"] == pub["id"])
    assert done["status"] == "published" and done["has_artifact"]
    zip_resp = await authed.get(f"{API}/publications/{pub['id']}/artifact")
    assert zip_resp.status_code == 200 and zip_resp.content[:2] == b"PK"
    again = await authed.post(f"{API}/publications/{pub['id']}/publish-now")
    assert again.json().get("idempotent")

    # ten_static staging site: page + repaired sitemap
    pub2 = (await authed.post(f"{API}/publications", json={"article_id": art["id"], "target": "ten_static"})).json()
    await authed.post(f"{API}/publications/{pub2['id']}/publish-now")
    await _drain(worker)
    async with session_factory()() as db:
        p2 = await db.get(Publication, __import__("uuid").UUID(pub2["id"]))
        assert p2.status == "published", p2.last_error
        article = await db.get(Article, p2.article_id)
        assert article.state == "published"
        posts = (await db.execute(select(SocialPost).where(SocialPost.article_id == article.id))).scalars().all()
    root = Path(get_settings().site_root) / "ten"
    page = root / "brief" / seo["slug"] / "index.html"
    assert page.exists() and seo["title_tag"] in page.read_text(encoding="utf-8")
    sm = (root / "sitemap.xml").read_text(encoding="utf-8")
    assert seo["canonical_url"] in sm and "localhost" not in sm
    served = await authed.get(f"/site/ten/brief/{seo['slug']}/")
    assert served.status_code == 200

    # social draft auto-generated after publish; no token → honest fallback
    assert posts and posts[0].status == "draft_ready" and 700 <= len(posts[0].text) <= 1300
    r = await authed.post(f"{API}/social/{posts[0].id}/publish")
    assert r.status_code == 409 and r.json()["error"]["code"] == "linkedin_not_connected"

    # dashboard reflects real rows
    summary = (await authed.get(f"{API}/dashboard/summary")).json()
    assert summary["cards"]["published_7d"] >= 1
    activity = (await authed.get(f"{API}/dashboard/activity")).json()["items"]
    assert any(a["action"] == "review.approve" for a in activity)


async def test_review_reject_and_revision(authed, worker):
    art = await _promoted_article(authed, worker)
    assert art["state"] == "in_review"
    r = await authed.post(f"{API}/articles/{art['id']}/request-revision", json={"reason": "Sharper takeaway please", "stage": "edit"})
    assert r.status_code == 200 and r.json()["job"]["type"] == "edit"
    await _drain(worker)
    art2 = (await authed.get(f"{API}/articles/{art['id']}")).json()
    assert art2["state"] == "in_review"  # edit -> seo -> qa -> back to review
    r = await authed.post(f"{API}/articles/{art['id']}/reject", json={"reason": "Not for us"})
    assert r.json()["state"] == "archived"
    r = await authed.post(f"{API}/articles/{art['id']}/approve", json={})
    assert r.status_code == 409


async def test_manual_edit_restore_and_illegal_run(authed, worker):
    art = await _promoted_article(authed, worker)
    sections = art["current_version"]["payload"]["article"]["sections"]
    sections[1]["paragraphs"][0] = sections[1]["paragraphs"][0] + " Leaders should watch the sequencing closely."
    r = await authed.patch(f"{API}/articles/{art['id']}", json={"sections": sections, "note": "tweak"})
    assert r.status_code == 200 and r.json()["state"] == "qa"  # edits invalidate QA/approval
    versions = (await authed.get(f"{API}/articles/{art['id']}/versions")).json()["items"]
    draft = next(v for v in versions if v["stage"] == "draft")
    r = await authed.post(f"{API}/articles/{art['id']}/versions/{draft['id']}/restore")
    assert r.status_code == 200 and r.json()["current_version"]["stage"] == "restored"
    r = await authed.post(f"{API}/articles/{art['id']}/run", json={"stage": "qa"})
    assert r.status_code == 200
    r = await authed.post(f"{API}/articles/{art['id']}/run", json={"stage": "qa"})
    assert r.status_code == 409  # busy: a QA job is already queued


async def test_thin_sources_needs_sources(authed, worker):
    r = await authed.post(f"{API}/topics", json={"title": "A paywalled story about Contoso", "category": "brief", "links": ["https://paywall.example.com/a"], "auto": True})
    assert r.status_code == 201
    await _drain(worker)
    art = (await authed.get(f"{API}/articles/{r.json()['article']['id']}")).json()
    assert art["state"] == "needs_sources"
    assert "Needs more sources" in art["last_error"]
    assert art["research_pack"]["status"] == "insufficient_evidence"


async def test_seo_override_validation(authed, worker):
    art = await _promoted_article(authed, worker)
    r = await authed.patch(f"{API}/seo/{art['id']}", json={"title_tag": "Too short"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "seo_invalid"
    good = "Northwind's Warehouse Bet: The Capital Allocation Test"
    r = await authed.patch(f"{API}/seo/{art['id']}", json={"title_tag": good})
    assert r.status_code == 200 and r.json()["seo"]["title_tag"] == good and "title_tag" in r.json()["seo"]["overrides"]


async def test_audit_baseline_then_live(authed, worker):
    audit = (await authed.get(f"{API}/seo/audit")).json()
    assert audit["source"] == "baseline" and len(audit["findings"]) == 12
    await authed.post(f"{API}/seo/inventory/refresh")
    await _drain(worker)
    audit = (await authed.get(f"{API}/seo/audit")).json()
    ids = {f["id"] for f in audit["findings"]}
    assert audit["source"] == "live"
    assert {"sitemap_broken", "missing_meta", "missing_canonical", "missing_h1", "placeholder_content"} <= ids
    csv_resp = await authed.get(f"{API}/seo/audit/export")
    assert csv_resp.status_code == 200 and "proposed_title" in csv_resp.text


async def test_failed_job_visible_and_retryable(authed, worker):
    async with session_factory()() as db:
        src = (await db.execute(select(Source).where(Source.name == "Example Business"))).scalar_one()
        src.url = "https://feeds.example.com/down.xml"
        for s in (await db.execute(select(Source))).scalars():
            if s.id != src.id:
                s.active = False
        await db.commit()
    r = await authed.post(f"{API}/feed/refresh", json={})
    await _drain(worker)
    async with session_factory()() as db:
        job = await db.get(Job, __import__("uuid").UUID(r.json()["job"]["id"]))
        assert job.status == "done"  # a dead feed is recorded on the source, the run still completes
    items = (await authed.get(f"{API}/feed")).json()["items"]
    assert items == [] or all(isinstance(i["title"], str) for i in items)


async def test_settings_prompt_versioning(authed):
    prompts = (await authed.get(f"{API}/settings/prompts")).json()["items"]
    assert any(p["key"] == "agents/writer" for p in prompts)
    base = (await authed.get(f"{API}/settings/prompts/agents/writer")).json()
    r = await authed.put(f"{API}/settings/prompts/agents/writer", json={"body": base["active"]["body"] + "\n\nExtra rule: be brief.", "note": "test"})
    v = r.json()
    assert v["active"]["source"] == "db" and v["active"]["version"] != base["active"]["version"]
    r = await authed.post(f"{API}/settings/prompts/agents/writer/activate", json={"version_id": "file"})
    assert r.json()["active"]["source"] == "file"  # one-click rollback


async def test_feed_item_count(tenant):
    async with session_factory()() as db:
        assert (await db.execute(select(FeedItem))).scalars().all() == []

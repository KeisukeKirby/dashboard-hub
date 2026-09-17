"""Build index.html for the dashboard hub.

catalog.json is the hand-written source of truth (names, areas, summaries).
This script only adds what goes stale: HTTP status, last deploy / push date,
thumbnails, and a list of Vercel projects and GitHub repos that the catalog
doesn't know yet.

    python build.py            # refresh status + dates, write index.html
    python build.py --shots    # ...and retake thumbnails (headless Chrome, writes blocked)
    python build.py --offline  # skip network, reuse dates written in catalog.json
"""
import base64
import concurrent.futures as cf
import datetime as dt
import hashlib
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent
THUMBS = ROOT / "thumbs"
# Artifact pages need a claude.ai login, so their HTML is fetched by Claude into
# artifact-src/<item id>/ and photographed locally. Not committed.
ARTIFACT_SRC = ROOT / "artifact-src"
# Artifact pages listed in catalog "pages" are copied to p/<id>/ and served by Vercel,
# so their hub links open without a claude.ai login.
PAGES = ROOT / "p"
THUMB_SIZE = (640, 400)
BKK = dt.timezone(dt.timedelta(hours=7))
STANDALONE_HEAD = (
    '<!doctype html>\n<html lang="ja">\n<meta charset="utf-8">\n'
    '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
    # internal pages: reachable by URL, but kept out of search results
    '<meta name="robots" content="noindex">\n'
)
# The Artifact host adds these base rules around every page.
ARTIFACT_HEAD = STANDALONE_HEAD + (
    "<style>body{margin:0}img{max-width:100%}[hidden]{display:none!important}</style>\n"
)
sys.stdout.reconfigure(encoding="utf-8")


def cli_json(*args):
    exe = shutil.which(args[0])
    if not exe:
        raise RuntimeError(f"{args[0]} が見つかりません")
    out = subprocess.run([exe, *args[1:]], capture_output=True, text=True, encoding="utf-8")
    if out.returncode != 0:
        raise RuntimeError(f"{' '.join(args)} failed: {out.stderr.strip()[-300:]}")
    text = out.stdout
    # vercel prints a banner before the JSON body
    start = min(i for i in (text.find("{"), text.find("[")) if i >= 0)
    return json.loads(text[start:])


def ms_to_date(ms):
    return dt.datetime.fromtimestamp(ms / 1000, BKK).date().isoformat()


def iso_to_date(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(BKK).date().isoformat()


def http_status(url):
    req = urllib.request.Request(url, headers={"User-Agent": "dashboard-hub-check"})
    try:
        with urllib.request.urlopen(req, timeout=20) as res:
            return res.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return 0


def classify(item, code):
    if item.get("host") == "artifact":
        return "artifact"  # needs a claude.ai login, can't be checked from here
    if not item.get("url"):
        return "none"
    if 200 <= code < 400:
        return "live"
    if code in (401, 403):
        return "locked"
    return "down"


def take_shots(items):
    from PIL import Image

    node = shutil.which("node")
    if not node:
        raise RuntimeError("node が見つかりません")
    THUMBS.mkdir(exist_ok=True)

    targets, staged = [], []
    for i in items:
        if i.get("archived"):
            continue
        if i["status"] == "live":
            targets.append({"id": i["id"], "url": i["url"]})
        elif i["status"] == "artifact":
            src = ARTIFACT_SRC / i["id"] / "index.html"
            if not src.exists():
                print(f"  ! サムネなし: {i['name']}({src.relative_to(ROOT)} がない)")
                continue
            # staged next to the source so relative asset paths still resolve
            page = src.with_name("_shot.html")
            page.write_text(ARTIFACT_HEAD + src.read_text(encoding="utf-8"), encoding="utf-8")
            staged.append(page)
            targets.append({"id": i["id"], "url": page.as_uri()})

    with tempfile.TemporaryDirectory() as tmp:
        tmp = pathlib.Path(tmp)
        (tmp / "targets.json").write_text(json.dumps(targets), encoding="utf-8")
        try:
            out = subprocess.run(
                [node, str(ROOT / "shots.mjs"), str(tmp / "targets.json"), str(tmp)],
                capture_output=True, text=True, encoding="utf-8",
            )
        finally:
            for page in staged:
                page.unlink(missing_ok=True)
        if out.returncode != 0:
            raise RuntimeError(f"shots.mjs failed: {out.stderr.strip()[-500:]}")

        for line in out.stdout.splitlines():
            r = json.loads(line)
            png = tmp / f"{r['id']}.png"
            if r.get("error") or not png.exists():
                print(f"  ! サムネ失敗: {r['id']} {r.get('error', '')}")
                continue
            with Image.open(png) as im:
                im.convert("RGB").resize(THUMB_SIZE, Image.LANCZOS).save(
                    THUMBS / f"{r['id']}.webp", "WEBP", quality=80, method=6
                )
            notes = []
            if not r["loaded"]:
                notes.append("load イベント待ちがタイムアウト")
            if r["blocked"]:
                notes.append(f"書き込み系リクエストを {len(r['blocked'])} 件遮断")
            print(f"  thumb: {r['id']}" + (f"({'、'.join(notes)})" if notes else ""))


def publish_pages(page_ids):
    for page_id in page_ids:
        src = ARTIFACT_SRC / page_id / "index.html"
        if not src.exists():
            # keep whatever copy is already committed in p/
            print(f"  ! ページ未更新: {page_id}({src.relative_to(ROOT)} がない)")
            continue
        out = PAGES / page_id / "index.html"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(ARTIFACT_HEAD + src.read_text(encoding="utf-8"), encoding="utf-8")


def attach_thumbs(items):
    for i in items:
        f = THUMBS / f"{i['id']}.webp"
        if f.exists() and not i.get("archived"):
            digest = hashlib.sha1(f.read_bytes()).hexdigest()[:8]
            i["thumb"] = f"thumbs/{f.name}?v={digest}"


def render(template, data):
    blob = json.dumps(data, ensure_ascii=False, indent=1).replace("<", "\\u003c")
    return template.replace("__HUB_DATA__", blob)


def main():
    offline = "--offline" in sys.argv
    catalog = json.loads((ROOT / "catalog.json").read_text(encoding="utf-8"))
    items = catalog["items"]
    publish_pages(catalog.get("pages", []))

    vercel, repos = {}, {}
    if not offline:
        scopes = set(catalog["watchScopes"]) | {
            i["vercel"].split("/")[0] for i in items if i.get("vercel")
        }
        for scope in sorted(scopes):
            for p in cli_json("vercel", "project", "ls", "--scope", scope, "--json")["projects"]:
                vercel[f"{scope}/{p['name']}"] = p
        owner = catalog["githubOwner"]
        for r in cli_json("gh", "repo", "list", owner, "--limit", "300", "--json", "name,pushedAt"):
            repos[f"{owner}/{r['name']}"] = r["pushedAt"]
        for i in items:
            repo = i.get("repo")
            if repo and repo not in repos:
                repos[repo] = cli_json("gh", "api", f"repos/{repo}")["pushed_at"]

        urls = [i["url"] for i in items if i.get("url") and i.get("host") != "artifact"]
        with cf.ThreadPoolExecutor(8) as pool:
            codes = dict(zip(urls, pool.map(http_status, urls)))
    else:
        codes = {}

    for i in items:
        if not offline:
            v = vercel.get(i.get("vercel", ""))
            if v:
                i["updated"] = ms_to_date(v["updatedAt"])
            elif repos.get(i.get("repo", "")):
                i["updated"] = iso_to_date(repos[i["repo"]])
        code = codes.get(i.get("url"), 200 if offline else 0)
        i["httpStatus"] = code
        i["status"] = classify(i, code)

    if "--shots" in sys.argv:
        if offline:
            raise RuntimeError("--shots は --offline と一緒に使えません(公開状態が必要)")
        take_shots(items)
    attach_thumbs(items)

    data = {
        "checkedAt": dt.datetime.now(BKK).isoformat(timespec="minutes"),
        "offline": offline,
        "areas": catalog["areas"],
        "kinds": catalog["kinds"],
        "items": items,
    }
    template = (ROOT / "template.html").read_text(encoding="utf-8")
    if "__HUB_DATA__" not in template:
        raise RuntimeError("template.html に __HUB_DATA__ がありません")

    # Static hosts (localhost, Vercel) send no charset header, so index.html declares it,
    # and thumbnails are separate files there.
    (ROOT / "index.html").write_text(STANDALONE_HEAD + render(template, data), encoding="utf-8")
    # The Artifact host wraps the page in its own doctype/head and serves a single
    # file, so artifact.html gets the bare body with thumbnails inlined.
    inline = json.loads(json.dumps(data))
    for i in inline["items"]:
        if i.get("thumb"):
            raw = (ROOT / i["thumb"].split("?")[0]).read_bytes()
            i["thumb"] = "data:image/webp;base64," + base64.b64encode(raw).decode()
    (ROOT / "artifact.html").write_text(render(template, inline), encoding="utf-8")

    with_thumb = sum(1 for i in items if i.get("thumb"))
    print(f"index.html: {len(items)} items ({with_thumb} with thumbnails), checked {data['checkedAt']}")
    for i in items:
        if i["status"] == "down" and not i.get("archived"):
            print(f"  ! 停止: {i['name']} ({i.get('url')}, HTTP {i['httpStatus']})")
    if not offline:
        known_v = {i["vercel"] for i in items if i.get("vercel")} | set(catalog.get("ignore", []))
        known_r = {i["repo"] for i in items if i.get("repo")} | set(catalog.get("ignore", []))
        watch = tuple(f"{s}/" for s in catalog["watchScopes"])
        new_v = sorted(k for k in vercel if k.startswith(watch) and k not in known_v)
        new_r = sorted(k for k in repos if k not in known_r)
        if new_v or new_r:
            print("カタログ未登録(catalog.json に追加するか ignore へ):")
            for k in new_v + new_r:
                print(f"  + {k}")


if __name__ == "__main__":
    main()

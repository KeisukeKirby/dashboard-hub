"""Build index.html for the dashboard hub.

catalog.json is the hand-written source of truth (names, areas, summaries).
This script only adds what goes stale: HTTP status, last deploy / push date,
and a list of Vercel projects and GitHub repos that the catalog doesn't know yet.

    python build.py            # refresh status + dates, write index.html
    python build.py --offline  # skip network, reuse dates written in catalog.json
"""
import concurrent.futures as cf
import datetime as dt
import json
import pathlib
import shutil
import subprocess
import sys
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent
BKK = dt.timezone(dt.timedelta(hours=7))
STANDALONE_HEAD = (
    '<!doctype html>\n<html lang="ja">\n<meta charset="utf-8">\n'
    '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
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


def main():
    offline = "--offline" in sys.argv
    catalog = json.loads((ROOT / "catalog.json").read_text(encoding="utf-8"))
    items = catalog["items"]

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

    data = {
        "checkedAt": dt.datetime.now(BKK).isoformat(timespec="minutes"),
        "offline": offline,
        "areas": catalog["areas"],
        "kinds": catalog["kinds"],
        "items": items,
    }
    blob = json.dumps(data, ensure_ascii=False, indent=1).replace("<", "\\u003c")
    html = (ROOT / "template.html").read_text(encoding="utf-8")
    if "__HUB_DATA__" not in html:
        raise RuntimeError("template.html に __HUB_DATA__ がありません")
    page = html.replace("__HUB_DATA__", blob)
    # The Artifact host wraps the page in its own doctype/head, so it gets the bare body.
    # Static hosts (localhost, Vercel) send no charset header, so index.html declares it.
    (ROOT / "artifact.html").write_text(page, encoding="utf-8")
    (ROOT / "index.html").write_text(STANDALONE_HEAD + page, encoding="utf-8")

    print(f"index.html: {len(items)} items, checked {data['checkedAt']}")
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

# dashboard-hub (Barefootinc Backroom)
## 概要
Keisuke が作ったダッシュボード・ツール・LP・Artifact を1ページで一覧する静的ページ。

## 技術スタック
Python 3(標準ライブラリのみ)でビルド → 自己完結の `index.html`。JS は素のまま、依存なし。
状態の取得に `vercel` CLI と `gh` CLI(どちらも認証済みが前提)を使う。

## コマンド
- ビルド: `python build.py`(公開状態・更新日を取り直して index.html を書き出す)
- サムネも撮り直す: `python build.py --shots`(ヘッドレス Chrome。`shots.mjs` が GET/HEAD/OPTIONS 以外を遮断するので本番 DB に書き込まない)
- ネットワークなしで見た目だけ確認: `python build.py --offline`
- デプロイ: main に push すると Vercel(barefootinc-th / barefootinc-backroom)が自動デプロイ。サイトに出るのは index.html と thumbs/ だけ(.vercelignore)
- プレビュー: `projects/.claude/launch.json` の `dashboard-hub`(python http.server 8124)

## 触ってはいけない領域
- `index.html`(localhost・Vercel 用、doctype と charset 付き)と `artifact.html`(Artifact 公開用、本文のみ)は生成物。直接編集せず `template.html` / `catalog.json` を直してビルドする

## このプロジェクト固有の規約
- 名前・分野・説明文は `catalog.json` に手で書く。自動取得するのは HTTP 状態・更新日だけ
- Artifact は claude.ai のログインが要るので状態確認の対象外。`updated` を手で更新する
- Artifact のサムネは、Claude が Artifact ツールでページ本体を `artifact-src/<item id>/index.html` に取得してから `--shots`。artifact-src/ は非公開の中身なのでコミットしない
- Artifact のサムネを公開ページに載せるのは 2026-09-16 に Keisuke が承認済み(10件すべて)
- catalog.json の `pages` に並べた Artifact は `p/<id>/index.html` に書き出して Vercel で公開し、カードのリンクもその URL にする(claude.ai のログインなしで開ける)。元の Artifact は links に残す。中身を更新したら artifact-src/ に取り込み直してビルド
- 公開ページ(店舗3D・フォトマップ・KL出張報告 日英)は 2026-09-17 に Keisuke が承認。出張報告は取引先の実名・評価・卸条件を含むと伝えた上での判断。販売実績の Artifact 版2件は Vercel 版と重複するので一覧から外した
- 公開ページとハブには noindex を付けている(URL を知っていれば誰でも読める点は変わらない)
- ビルド時に「カタログ未登録」と出たものは、載せるなら items へ、載せないなら ignore へ入れる
- 推測で書いた説明には「推定」と明記する

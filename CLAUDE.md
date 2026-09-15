# dashboard-hub (Barefootinc Backroom)
## 概要
Keisuke が作ったダッシュボード・ツール・LP・Artifact を1ページで一覧する静的ページ。

## 技術スタック
Python 3(標準ライブラリのみ)でビルド → 自己完結の `index.html`。JS は素のまま、依存なし。
状態の取得に `vercel` CLI と `gh` CLI(どちらも認証済みが前提)を使う。

## コマンド
- ビルド: `python build.py`(公開状態・更新日を取り直して index.html を書き出す)
- ネットワークなしで見た目だけ確認: `python build.py --offline`
- プレビュー: `projects/.claude/launch.json` の `dashboard-hub`(python http.server 8124)

## 触ってはいけない領域
- `index.html`(localhost・Vercel 用、doctype と charset 付き)と `artifact.html`(Artifact 公開用、本文のみ)は生成物。直接編集せず `template.html` / `catalog.json` を直してビルドする

## このプロジェクト固有の規約
- 名前・分野・説明文は `catalog.json` に手で書く。自動取得するのは HTTP 状態・更新日だけ
- Artifact は claude.ai のログインが要るので状態確認の対象外。`updated` を手で更新する
- ビルド時に「カタログ未登録」と出たものは、載せるなら items へ、載せないなら ignore へ入れる
- 推測で書いた説明には「推定」と明記する

# Barefootinc Backroom (dashboard-hub)

Barefoot Inc(タイ・マレーシア)向けに作ったダッシュボード・ツール・LP・Artifact を、1ページで一覧する静的ページ。
分野・国での絞り込み、検索、公開状態(公開中 / 認証あり / 停止)と最終更新日、要確認事項を表示する。

公開 URL: https://barefootinc-backroom.vercel.app (Vercel チーム barefootinc-th / プロジェクト barefootinc-backroom)

## 更新のしかた

1. `catalog.json` に項目を追加・修正する(名前・分野・説明は手書き)
2. `python build.py` を実行する。`vercel` と `gh` の CLI が認証済みであること
   - 公開状態と更新日を取り直して `index.html`(サイト用)と `artifact.html`(Claude Artifact 用)を書き出す
   - カタログに載っていない Vercel プロジェクト・GitHub リポジトリがあれば表示する
3. コミットして main に反映すると、Vercel が再デプロイする

`index.html` と `artifact.html` は生成物なので直接編集しない。見た目は `template.html` で変える。

Artifact(claude.ai)へのリンクは、claude.ai にログインした本人しか開けない。

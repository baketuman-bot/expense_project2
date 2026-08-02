# サイドメニュー表示/非表示トグルボタン Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 左上のハンバーガーボタンを押すたびにサイドメニュー(`.precision-sidebar`)の表示/非表示を切り替え、状態を `localStorage` に保存してページ遷移後も保持する。

**Architecture:** `body` 要素の `sidebar-hidden` クラスの有無でCSSの表示/非表示を制御する。サーバー往復なしの純クライアントサイドJS。ページ読み込み直後のチラつき(FOUC)を防ぐため、`<body>` 開始タグ直後に同期的なインラインscriptで `localStorage` を読み `sidebar-hidden` クラスを即時付与する。

**Tech Stack:** Django テンプレート (`base.html`)、素のJS（フレームワークなし）、CSS (`swiss.css`)。既存の Bootstrap 5 バンドルJSは使わない。

## Global Constraints

- 本番DB (`expense_db`) 直結のプロジェクトのため、検証は読み取り専用で行う（`DELETE`/`TRUNCATE`/`flush` 等は一切実行しない） — 仕様書 `docs/superpowers/specs/2026-08-02-sidebar-toggle-button-design.md` および `CLAUDE.md` より
- サーバーへの往復は不要（純クライアントサイドの見た目の切り替え） — 仕様書より
- 対象は PC・スマホ共通（全画面幅） — 仕様書より
- 非表示時はサイドバーが完全に消え、本文(`.precision-main`)が幅一杯になる（アイコンのみの折りたたみは実装しない） — 仕様書より
- 状態は `localStorage`（キー `sidebarHidden`、値 `'1'`/`'0'`）に保存し、ページ遷移・再訪問後も保持する — 仕様書より
- 本番反映には systemd の `expense_project2-uvicorn` 再起動が必要で、Claudeはsudoパスワードを持たないため再起動できない。検証は `RequestFactory` によるレンダリング結果を静的HTMLとして保存し、ヘッドレスブラウザで確認する方式で行う

---

### Task 1: サイドバートグルボタンの実装（HTML/CSS/JS）と検証

**Files:**
- Modify: `expenses/templates/expenses/base.html`
- Modify: `expenses/static/expenses/swiss.css`
- Test: 自動テストなし。手動検証はスクラッチパッド配下に生成する一時HTML/スクリーンショットで行う（リポジトリには残さない）

**Interfaces:**
- Consumes: なし（既存テンプレート構造のみ利用）
- Produces: `#sidebarToggleBtn`（ボタンID）、`body.sidebar-hidden` クラス、`localStorage['sidebarHidden']`。後続タスクなし（本機能はこれ単体で完結）

- [ ] **Step 1: `swiss.css` にトグルボタンのスタイルを追加**

`expenses/static/expenses/swiss.css` の90行目 `.corp-banner-brand a:hover{ opacity:.85; }` の直後（91行目 `.corp-banner-sub{...}` の手前）に以下を追記する。

Edit対象（old_string）:
```css
.corp-banner-brand a:hover{ opacity:.85; }
.corp-banner-sub{ font-weight:500; opacity:.7; margin-left:4px; }
```

置換後（new_string）:
```css
.corp-banner-brand a:hover{ opacity:.85; }
.sidebar-toggle-btn{
  background:transparent;
  border:none;
  color:#fff;
  display:inline-flex;
  align-items:center;
  justify-content:center;
  width:32px;height:32px;
  margin-right:8px;
  border-radius:4px;
  cursor:pointer;
  flex-shrink:0;
}
.sidebar-toggle-btn:hover{ background:rgba(255,255,255,.15); }
.sidebar-toggle-btn:focus-visible{ outline:2px solid #fff; outline-offset:1px; }
.corp-banner-sub{ font-weight:500; opacity:.7; margin-left:4px; }
```

- [ ] **Step 2: `swiss.css` に非表示状態のレイアウトルールを追加**

同ファイルの166行目 `body.no-sidebar .precision-sidebar{display:none;}` の直後に以下を追記する。

Edit対象（old_string）:
```css
body.no-sidebar .precision-sidebar{display:none;}
```

置換後（new_string）:
```css
body.no-sidebar .precision-sidebar{display:none;}
body.sidebar-hidden .precision-sidebar{ display:none; }
```

続けて、同ファイルの376行目 `body.has-sidebar .precision-main{ margin-left:var(--precision-sidebar-width); }` の直後に以下を追記する。

Edit対象（old_string）:
```css
body.has-sidebar .precision-main{ margin-left:var(--precision-sidebar-width); }
.precision-shell{ max-width:1200px; margin:0 auto; }
```

置換後（new_string）:
```css
body.has-sidebar .precision-main{ margin-left:var(--precision-sidebar-width); }
body.sidebar-hidden.has-sidebar .precision-main{ margin-left:0; }
.precision-shell{ max-width:1200px; margin:0 auto; }
```

- [ ] **Step 3: `base.html` に FOUC 防止のインラインscriptを追加**

`expenses/templates/expenses/base.html` の21行目 `<body class="precision ...">` の直後（22行目 `{% if user.is_authenticated %}` の手前）に以下を追記する。

Edit対象（old_string）:
```html
<body class="precision {% if user.is_authenticated %}has-sidebar{% else %}no-sidebar{% endif %} {% block body_class %}{% endblock %}">
    {% if user.is_authenticated %}
```

置換後（new_string）:
```html
<body class="precision {% if user.is_authenticated %}has-sidebar{% else %}no-sidebar{% endif %} {% block body_class %}{% endblock %}">
    <script>
    (function(){
        try{
            if(localStorage.getItem('sidebarHidden') === '1'){
                document.body.classList.add('sidebar-hidden');
            }
        }catch(e){}
    })();
    </script>
    {% if user.is_authenticated %}
```

- [ ] **Step 4: `base.html` にトグルボタンのマークアップを追加**

同ファイルの `<div class="corp-banner-content">` の直後、`<div class="corp-banner-brand">` の手前にボタンを追加する。

Edit対象（old_string）:
```html
        <div class="corp-banner-content">
            <div class="corp-banner-brand">
```

置換後（new_string）:
```html
        <div class="corp-banner-content">
            <button type="button" class="sidebar-toggle-btn" id="sidebarToggleBtn"
                    aria-label="サイドメニューの表示切替" aria-pressed="false">
                <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M3 6h18"></path>
                    <path d="M3 12h18"></path>
                    <path d="M3 18h18"></path>
                </svg>
            </button>
            <div class="corp-banner-brand">
```

- [ ] **Step 5: `base.html` にクリックハンドラのJSを追加**

同ファイルの既存の `DOMContentLoaded` スクリプトブロック（アコーディオン自動展開処理）に、トグルボタンの初期化とクリックハンドラを追記する。

Edit対象（old_string）:
```html
    <script>
    // アクティブリンクを含むアコーディオングループを自動展開
    document.addEventListener('DOMContentLoaded', function() {
        document.querySelectorAll('.precision-group-toggle').forEach(function(btn) {
            var targetId = btn.getAttribute('data-bs-target');
            var collapseEl = document.querySelector(targetId);
            if (collapseEl && collapseEl.querySelector('.precision-link.is-active')) {
                btn.classList.remove('collapsed');
                btn.setAttribute('aria-expanded', 'true');
                collapseEl.classList.add('show');
            }
        });
    });
    </script>
```

置換後（new_string）:
```html
    <script>
    // アクティブリンクを含むアコーディオングループを自動展開
    document.addEventListener('DOMContentLoaded', function() {
        document.querySelectorAll('.precision-group-toggle').forEach(function(btn) {
            var targetId = btn.getAttribute('data-bs-target');
            var collapseEl = document.querySelector(targetId);
            if (collapseEl && collapseEl.querySelector('.precision-link.is-active')) {
                btn.classList.remove('collapsed');
                btn.setAttribute('aria-expanded', 'true');
                collapseEl.classList.add('show');
            }
        });

        // サイドメニューの表示/非表示トグル
        var sidebarToggleBtn = document.getElementById('sidebarToggleBtn');
        if (sidebarToggleBtn) {
            sidebarToggleBtn.setAttribute('aria-pressed', document.body.classList.contains('sidebar-hidden') ? 'true' : 'false');
            sidebarToggleBtn.addEventListener('click', function() {
                var hidden = document.body.classList.toggle('sidebar-hidden');
                sidebarToggleBtn.setAttribute('aria-pressed', hidden ? 'true' : 'false');
                try {
                    localStorage.setItem('sidebarHidden', hidden ? '1' : '0');
                } catch (e) {}
            });
        }
    });
    </script>
```

- [ ] **Step 6: Django構文チェック**

Run:
```powershell
wsl.exe -d Ubuntu-24.04 -- bash -lc "cd /home/idc_user/expense_project2 && .venv/bin/python manage.py check"
```
Expected: `System check identified no issues (0 silenced).`（テンプレート構文エラーがあればここで検知される）

- [ ] **Step 7: レンダリング結果を静的HTMLとして保存**

`verify` スキルの方式に従い、DB書き込みなしで `expense_list` 画面を1件レンダリングし、ファイルに保存する。以下のPythonスクリプトを一時ファイルとして書き出し、WSL側で実行する。

`/home/idc_user/expense_project2/render_sidebar_check.py`（スクラッチパッド用の一時スクリプト。検証後に削除する）:
```python
import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'expense_project.settings')
django.setup()
from django.test import RequestFactory
from expenses import views
from expenses.models import M_User

rf = RequestFactory()
req = rf.get('/list/')
req.user = M_User.objects.filter(is_active=True).first()
resp = views.expense_list(req)
html = resp.content.decode('utf-8')

# file:// で開けるように static 参照をソースの静的ファイルパスへ書き換える
html = html.replace(
    '/static/expenses/swiss.css',
    'file:///home/idc_user/expense_project2/expenses/static/expenses/swiss.css'
)

out_path = '/home/idc_user/expense_project2/sidebar_check.html'
with open(out_path, 'w', encoding='utf-8') as f:
    f.write(html)
print('written:', out_path)
```

Run:
```powershell
wsl.exe -d Ubuntu-24.04 -- bash -lc "cd /home/idc_user/expense_project2 && .venv/bin/python render_sidebar_check.py"
```
Expected: `written: /home/idc_user/expense_project2/sidebar_check.html`

- [ ] **Step 8: 初期表示（サイドバー表示状態）のスクリーンショットを確認**

Run:
```powershell
& "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" --headless --disable-gpu --window-size=1280,900 --screenshot="C:\Users\idc_user\AppData\Local\Temp\claude\--wsl-localhost-Ubuntu-24-04-home-idc-user-expense-project2\2b5516e7-1b21-4c63-98dd-b10c5fad1817\scratchpad\sidebar_default.png" "\\wsl.localhost\Ubuntu-24.04\home\idc_user\expense_project2\sidebar_check.html"
```

Read ツールで `sidebar_default.png` を開き、以下を目視確認する:
- 左上にハンバーガーアイコンのボタンが表示されている
- サイドメニューが表示されている（幅232px程度で左に固定）
- レイアウトが崩れていない（既存の見た目から変化していない）

- [ ] **Step 9: クリック後（サイドバー非表示状態）のスクリーンショットを確認**

`sidebar_check.html` を複製し、ページ読み込み後に自動でトグルボタンをクリックするscriptを末尾に追加した検証用ファイルを作る（実際のクリックハンドラをそのまま実行させることで、実装コードを直接検証する）。

Run（WSL側でコピー＆追記):
```powershell
wsl.exe -d Ubuntu-24.04 -- bash -lc "cd /home/idc_user/expense_project2 && cp sidebar_check.html sidebar_check_clicked.html && sed -i 's#</body>#<script>window.addEventListener(\"load\", function(){ document.getElementById(\"sidebarToggleBtn\").click(); });</script></body>#' sidebar_check_clicked.html"
```

Run（スクリーンショット撮影）:
```powershell
& "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" --headless --disable-gpu --window-size=1280,900 --screenshot="C:\Users\idc_user\AppData\Local\Temp\claude\--wsl-localhost-Ubuntu-24-04-home-idc-user-expense-project2\2b5516e7-1b21-4c63-98dd-b10c5fad1817\scratchpad\sidebar_hidden.png" "\\wsl.localhost\Ubuntu-24.04\home\idc_user\expense_project2\sidebar_check_clicked.html"
```

Read ツールで `sidebar_hidden.png` を開き、以下を目視確認する:
- サイドメニューが完全に消えている
- 本文エリアが画面幅一杯に広がっている（左マージンがなくなっている）
- ハンバーガーボタン自体は引き続き左上に表示されている

- [ ] **Step 10: 一時検証ファイルを削除**

Run:
```powershell
wsl.exe -d Ubuntu-24.04 -- bash -lc "cd /home/idc_user/expense_project2 && rm -f render_sidebar_check.py sidebar_check.html sidebar_check_clicked.html"
```
Expected: エラーなく終了。`git status` でこれらのファイルがリポジトリに残っていないことを確認する。

- [ ] **Step 11: コミット**

```bash
git add expenses/templates/expenses/base.html expenses/static/expenses/swiss.css
git commit -m "feat: サイドメニューの表示/非表示を切り替えるトグルボタンを追加"
```

- [ ] **Step 12: 本番反映の依頼**

このタスクはテンプレート/CSS/JSの変更のみで、`python manage.py check` は反映確認の役に立たない（uvicornプロセスが再起動されるまで本番には反映されない）。ユーザーに `deploy\restart-uvicorn.bat` の実行、または `! wsl -d Ubuntu-24.04 -- sudo systemctl restart expense_project2-uvicorn` の実行を依頼する。

---

## Self-Review Notes

- **Spec coverage:** 仕様書の要件（左上配置・全画面幅対応・完全非表示・localStorage永続化・FOUC対策・サーバー往復なし）はすべて Task 1 の Step 1〜5 でカバーしている。テスト方針（DevToolsでの768px確認、アコーディオン非破壊確認）はStep 8〜9で代替（ヘッドレス環境のため実サーバーでのDevTools確認は本タスク外、ユーザーへの依頼事項として明記）
- **Placeholder scan:** なし。全ステップに実コードと実コマンドを記載
- **Type/identifier consistency:** ボタンID `sidebarToggleBtn`、クラス `sidebar-toggle-btn`／`sidebar-hidden`、localStorageキー `sidebarHidden` は全ステップで統一

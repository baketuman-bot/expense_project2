# サイドメニュー表示/非表示トグルボタン 設計書

- 日付: 2026-08-02
- 対象: `expenses/templates/expenses/base.html`, `expenses/static/expenses/swiss.css`

## 背景・目的

現在、左サイドバー（`.precision-sidebar`）はログイン中の全画面で常時表示されており、非表示にする手段がない。画面を広く使いたい場面のために、左上のボタンを押すたびにサイドバーの表示/非表示を切り替えられるようにする。

## 要件

- ボタンは左上（`corp-banner` 内、ロゴの左側）に設置し、ハンバーガーアイコンで表す
- 押すたびに表示/非表示をトグルする
- 対象は PC・スマホ共通（全画面幅）
- 非表示時はサイドバーが完全に消え、本文（`.precision-main`）が幅一杯になる
- 表示/非表示の状態は `localStorage` に保存し、ページ遷移・ブラウザの再訪問後も保持する
- サーバーへの往復は不要（純粋にクライアントサイドの見た目の切り替え）

## 非対象・現状維持

- サイドバー内のグループ開閉（アコーディオン、`.precision-group-toggle`）の挙動は変更しない
- スマホ幅（768px以下）での現状の積み重ね表示レイアウト自体は変更しない（非表示にした場合は単に丸ごと消える）
- アイコンをアイコンのみの細いバーに縮小する「折りたたみ」動作は実装しない（完全非表示のみ）

## 設計

### 状態管理

`body` 要素に `sidebar-hidden` クラスがあるかどうかで状態を表現する。

- `localStorage.getItem('sidebarHidden') === '1'` なら非表示状態
- クリック時に `body.classList.toggle('sidebar-hidden')` し、結果に応じて `localStorage.setItem('sidebarHidden', '1' or '0')`

### チラつき防止（FOUC対策）

サーバーレンダリングのため、ページ読み込み時に一瞬サイドバーが表示されてから消える現象を防ぐ必要がある。`<body ...>` 開始タグの直後、サイドバーのHTMLが解析される前に、同期的な `<script>` を置いて `localStorage` を読み取り、必要なら即座に `sidebar-hidden` クラスを `body` に付与する。

```html
<body class="...">
<script>
(function(){
  try{
    if(localStorage.getItem('sidebarHidden') === '1'){
      document.body.classList.add('sidebar-hidden');
    }
  }catch(e){}
})();
</script>
```

`try/catch` はプライベートブラウジング等で `localStorage` アクセスが例外を投げる環境への保険。

### ボタンの配置とマークアップ

`corp-banner-content` 内、`corp-banner-brand` の直前にボタンを追加する（`user.is_authenticated` ブロック内なので、未ログイン時は自動的に表示されない）。

```html
<button type="button" class="sidebar-toggle-btn" id="sidebarToggleBtn"
        aria-label="サイドメニューの表示切替" aria-pressed="false">
    <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor"
         stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M3 6h18"></path>
        <path d="M3 12h18"></path>
        <path d="M3 18h18"></path>
    </svg>
</button>
```

`aria-pressed` はJS側でクリック時・初期化時に実際の状態と同期させる。

### CSS追加（`swiss.css`）

```css
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

body.sidebar-hidden .precision-sidebar{ display:none; }
body.sidebar-hidden.has-sidebar .precision-main{ margin-left:0; }
```

配置場所: 既存の `.precision-sidebar` 定義（151行目付近）の直後、または `.precision-main` 定義（370行目付近）の直後にまとめて追記する。

### JS（トグル処理）

既存の `DOMContentLoaded` スクリプトブロック（アコーディオン自動展開の隣）に追記する。

```js
document.addEventListener('DOMContentLoaded', function() {
    var toggleBtn = document.getElementById('sidebarToggleBtn');
    if (toggleBtn) {
        toggleBtn.setAttribute('aria-pressed', document.body.classList.contains('sidebar-hidden') ? 'true' : 'false');
        toggleBtn.addEventListener('click', function() {
            var hidden = document.body.classList.toggle('sidebar-hidden');
            toggleBtn.setAttribute('aria-pressed', hidden ? 'true' : 'false');
            try {
                localStorage.setItem('sidebarHidden', hidden ? '1' : '0');
            } catch (e) {}
        });
    }
});
```

### データフロー

1. ページ読み込み → `<body>` 直後のインラインscriptが `localStorage` を読み、必要なら `sidebar-hidden` クラスを即時付与（チラつきなし）
2. `DOMContentLoaded` 後、ボタンの `aria-pressed` を実際の状態に同期
3. ボタンクリック → `body` のクラス切替（即時反映、リロード不要）→ CSSで `.precision-sidebar` / `.precision-main` の表示が変わる → `localStorage` に保存
4. 別ページへ遷移 → サーバーが同じ `base.html` を再レンダリング → 手順1に戻る

## 影響範囲

- `base.html` を継承する全ログイン後画面（`{% block sidebar %}` を上書きしていない画面すべて）に反映される
- ログイン画面（`no-sidebar`）には影響しない（`corp-banner` 自体が非表示のため）

## テスト方針

自動テストは追加しない（純粋な見た目のトグル、サーバーサイドロジック変更なし）。`verify` スキルの手順に沿って実際にブラウザで以下を確認する:

- ボタンクリックでサイドバーが表示/非表示になり、本文の幅が追従すること
- 非表示状態でページ遷移してもチラつかず非表示が維持されること
- 非表示状態でブラウザをリロードしても維持されること
- スマホ幅（DevToolsで768px以下に）でも同様に動作すること
- 既存のサイドバー内アコーディオン開閉（グループの展開）が壊れていないこと

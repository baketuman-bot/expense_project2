# 精算処理メニュー「仕訳出力」カード追加 設計

日付: 2026-07-06

## 背景

精算処理メニュー(`settlement_menu`)の仕訳処理セクションには「仕訳作成」カード(→ `journal_entry`)のみがあり、仕訳入力済み(`journal_done=True`)データの一覧・Excel出力画面(`settlement_journal`)へはメニューから直接遷移できない(`journal_entry` 画面内のボタン経由のみ)。

## 要件

- 精算処理メニューから、仕訳が確定(入力済み)したデータ一覧(既存の「仕訳出力」画面)へ直接遷移できるメニューカードを追加する。
- 対象件数をバッジ表示する。処理待ちを示す赤バッジと区別するため緑系の配色とする。

## 変更内容

### 1. `expenses/views.py` — `settlement_menu` ビュー

`counts` 辞書に `journal_done` を追加:

```python
'journal_done': base_qs.filter(settle_kbn__in=journal_kbns, journal_done=True).count(),
```

条件は既存の `settlement_journal` ビューの表示条件(FNS + 仕訳対象区分 + `journal_done=True`)と一致させる。

### 2. `expenses/templates/expenses/settlement_menu.html` — 仕訳処理セクション

「仕訳作成」カードの隣に「仕訳出力」カードを追加:

- リンク先: `{% url 'expenses:settlement_journal' %}`
- アイコン: `fa-file-excel`
- タイトル: 仕訳出力 / 説明文: 入力済の仕訳データ一覧・Excel出力
- バッジ: `counts.journal_done`(緑系: 背景 `#dcfce7`・文字 `#166534`)

## 変更しないもの

- `settlement_journal` ビュー・テンプレート・URL・モデル。既存画面に「精算処理メニューへ」の戻りリンクがあり導線は完結している。

## テスト・検証

- 本番DB直結のため Django テストランナーは使用しない(CLAUDE.md の制約)。
- `python manage.py check` とテンプレートレンダリングの目視確認(開発サーバー)で検証する。

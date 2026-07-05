# 仕訳明細の分割機能 設計書

作成日: 2026-07-06

## 目的

仕訳入力（精算処理 > 仕訳入力）で、1つの申請明細を複数の勘定科目・税区分に分けて仕訳できるようにする。
例: 会議費 11,000円 の明細を「会議費 8,000円（税区分12）」と「交際費 3,000円（税区分312）」の2仕訳行に分割する。

## 方針（決定事項）

- **明細行複製方式**: `T_DocumentContent` の行自体を複製して分割行を作る（案A）。
  既存の仕訳入力UI・保存API・Excel出力（`v_journaldocuments`）が「1行=1仕訳行」の前提のまま最小改修で動く。
- **申請データは不変**: 元行の `amount` / `consumption_tax` は書き換えない。分割は仕訳フィールド
  （`journal_amont` 等）のみで行い、分割行は申請側の全画面（詳細・一覧・CSV・合計）から除外する。
- **分割UI**: 仕訳入力3ペイン画面の「分割」ボタンで行追加、金額は手入力。N分割可。分割行は削除可能。
- **借方科目**: 分割行のみ変更可能。元行の科目は申請どおり固定。
- **貸方**: 元行に税込全額を残す。分割行の貸方は空とし、**分割行の右ペインに貸方入力欄は表示しない**
  （手入力も不要）。伝票単位の貸借は「借方 8,000+3,000+税 ⇔ 貸方 11,000」で成立し、
  既存の貸方集約ロジック（`_aggregate_journal_credit_rows`）は無改修。

## 1. データモデル

### 1-1. フィールド追加（migration 0088）

```python
class T_DocumentContent(models.Model):
    ...
    split_from = models.ForeignKey(
        'self', null=True, blank=True,
        on_delete=models.CASCADE,
        db_column='split_from_id',
        related_name='splits',
        verbose_name='分割元明細',
    )
```

- 非破壊的な `AddField` のみ。元行が消えれば分割行もCASCADE削除される
  （元行は申請明細なので通常削除されない。管理者の強制削除時は文書ごとCASCADEで一括削除）。
- MySQLコレーション統一ルールに従い、必要なら `utf8mb4_unicode_ci` を確認（カラム追加のみなので影響なし想定）。

### 1-2. マネージャによる分割行の除外

```python
class DocumentContentManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(split_from__isnull=True)

class T_DocumentContent(models.Model):
    objects     = DocumentContentManager()   # デフォルト: 分割行を除外
    all_objects = models.Manager()           # 全件（仕訳系ビュー専用）
```

- Django の逆参照マネージャ（`expense.contents.all()`）はデフォルトマネージャのフィルタを継承するため、
  **申請詳細・承認画面・合計計算（`models.py` の total 計算含む）・データ出力CSV・精算処理一覧など
  既存の申請側コードは無改修で分割行が見えなくなる**。
- `all_objects` に切り替えるのは仕訳系5ビューのみ:
  `settlement_journal` / `journal_entry` / `journal_detail_api` / `journal_save` / `journal_csv`。
  `journal_detail_api` / `journal_save` の `get_object_or_404` も `T_DocumentContent.all_objects` を使う
  （デフォルトマネージャのままだと分割行が404になる）。
- サイドバーのバッジ件数（`context_processors.settlement_pending_count`）は現状マネージャのまま
  = 分割行を含めない（元行が未入力なら1件としてカウントされるため実用上十分）。

## 2. 分割行の作成・削除API

### 2-1. 作成: `POST /settings/settlement/journal/<pk>/split/`（`journal_split`）

- `pk` は元行（`split_from__isnull=True`）であること。分割行を指定した場合は400
  （分割行の再分割＝ネストは禁止）。
- 新規 `T_DocumentContent` を作成:
  - コピー: `document`, `date`, `settle_kbn`, `shiharaisaki`, `purpose`, `tekikaku_cd`,
    `corpo_card`, `corpo_card_no`, `consumption_kbn`, `account`（初期値は元行と同じ科目）
  - `amount` / `consumption_tax` = **NULL**（申請金額は元行にのみ存在＝申請データ不変の担保）
  - 仕訳フィールドは全て空、`journal_done=False`、`split_from=元行`
- 何回でも実行可能（N分割）。
- レスポンス: 新行の一覧表示用データ（pk, 科目名, settle_label 等）をJSONで返し、
  フロントで中央ペインの元行直下に行を挿入する。

### 2-2. 削除: `POST /settings/settlement/journal/<pk>/delete/`（`journal_split_delete`）

- **`split_from` が NULL でないことをサーバー側で検証してから削除**
  （申請明細を誤削除しないガード。本番DBのため厳格に。NULLなら400）。
- フロント側は削除前に確認ダイアログを表示。

### 2-3. 権限

既存の仕訳系ビューと同じ `@login_required`（現行踏襲）。

## 3. 仕訳入力UI（`settlement_journal_entry.html`）

### 3-1. 中央ペイン（明細一覧）

- 元行に **[分割]** ボタンを追加。
- 分割行は元行の直下にインデント表示（`↳ 分割1`, `↳ 分割2` …）+ **[削除]** ボタン。
- 分割行の金額列は `journal_amont`（入力済みなら）を表示。未入力は空欄。
- ヘッダの件数（total/done/todo）は分割行も1件としてカウント。

### 3-2. 右ペイン（分割行選択時）

- **借方科目を選択可能**（`M_Account` からの選択）。選択値は `content.account` に保存するため、
  5桁変換（`_build_account_cd_5`）・科目名表示・`v_journaldocuments` は既存ロジックがそのまま効く。
  科目変更時は補助科目候補（`M_AccountSub`）も選び直せるよう再取得する。
- 元行選択時の右ペインは従来どおり（科目は申請どおり固定・変更不可）。
- 税区分・税率・借方金額・借方税額・借方適用は通常どおり入力。
- **貸方セクションは分割行では非表示**（入力欄を出さない。保存時も貸方フィールドは空のまま）。
- 参照エリア（左）: 分割行選択時も元行の申請情報・添付を表示する
  （分割行自身には添付がないため、`split_from` を辿って元行の添付を返す）。

### 3-3. 保存時の必須チェック（`journal_save`）

- 元行: 現行どおり8項目。
- 分割行: 貸方系3項目（`account_cd_cre`, `journal_amount_cre`, `journal_discription_cre`）を
  必須チェックから除外。借方系（税抜金額・消費税・税区分・税率・借方適用）のみで `journal_done` 判定。
- 分割行のみ `account_cd`（借方科目変更）をPOSTで受け付けて `content.account` を更新する。
  元行に対する `account_cd` のPOSTは無視する。

### 3-4. 合計チェック（警告のみ）

- 元行＋分割行の（`journal_amont` + `journal_tax`）合計が、元行の税込金額（外貨は円換算後）と
  一致しないとき ⚠警告バッジを表示。**保存はブロックしない**。

## 4. Excel出力・仕訳出力一覧

### 4-1. `v_journaldocuments`（DBビュー）

- 分割行も `T_DocumentContent` の実レコードなのでビューには自然に現れる（大改修不要）。
- ビューに `split_from_id` 列を追加し、`journal_csv` のSQLの ORDER BY を
  `document_id, COALESCE(split_from_id, document_detail_id), document_detail_id` に変更して
  「元行の直後に分割行」の順で出力する。

### 4-2. 伝票集約（`_aggregate_journal_credit_rows`）

- 変更不要。分割行の貸方は全列空なので集約対象外（既存の空行スキップに乗る）。
- 借方行数が増える分、貸方は先頭行から詰められる既存動作のままで問題ない。

### 4-3. 仕訳出力一覧（`settlement_journal.html`・入力済一覧）

- 分割行も行として表示（`↳` 表示で元行との親子が分かるように）。
- **元行のチェックボックスと分割行のチェックを連動**させる（片方だけ出力される事故を防ぐ）。

## 5. テスト

`test_expense_db` を使用（本番DB `expense_db` でのテスト実行は厳禁）。

- 分割作成API: 元行から作成できる／分割行を指定すると400／コピー項目と NULL 項目の検証
- 分割削除API: 分割行は削除できる／元行（split_from=NULL）を指定すると400で削除されない
- マネージャ除外: 分割行が `document.contents` / 申請詳細 / 合計金額 / データ出力CSVに現れないこと
- `journal_save`: 分割行は貸方なしで `journal_done=True` になる／元行は従来どおり貸方必須
- `journal_csv`: 分割行が出力に含まれ、元行の直後に並ぶこと

## 6. 影響範囲まとめ

| 箇所 | 変更 |
|---|---|
| `models.py` | `split_from` 追加・マネージャ2本化 |
| migration 0088 | `AddField` のみ（非破壊） |
| `views.py` | 仕訳系5ビューを `all_objects` 化、`journal_split` / `journal_split_delete` 新設、`journal_save` の必須チェック分岐＋科目更新、`journal_csv` の ORDER BY 変更 |
| `urls.py` | ルート2本追加 |
| `settlement_journal_entry.html` | 分割・削除ボタン、分割行表示、右ペインの科目選択／貸方非表示、合計警告 |
| `settlement_journal.html` | 分割行表示・チェック連動 |
| `v_journaldocuments`（DBビュー） | `split_from_id` 列追加 |
| 申請側の画面・CSV | **無改修**（マネージャで自動除外） |

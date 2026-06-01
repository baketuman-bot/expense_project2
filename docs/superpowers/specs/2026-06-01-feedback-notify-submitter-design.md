# 設計ドキュメント: 改善要望 更新時の提出者メール通知

**日付:** 2026-06-01  
**対象機能:** 改善要望 (`/feedback/<id>/edit/`)

---

## 概要

管理者（`admin` ロール）が改善要望を更新する際に、提出者へのメール通知可否を管理者自身が選択できるようにする。

---

## 要件

- 管理者が `feedback_edit` フォームの保存ボタンを押したとき、確認モーダルを表示する
- モーダルで「通知して保存」または「通知せずに保存」を選択できる
- 「通知して保存」を選んだ場合、提出者のメールアドレスへ更新通知を送信する
- 提出者自身が自分の要望を編集する場合（`is_admin=False`）はモーダルを表示しない

---

## フロントエンド設計

### 変更ファイル
- `expenses/templates/expenses/feedback_form.html`

### 動作

1. 管理者が保存ボタンをクリック → フォームの `submit` イベントをキャンセル
2. Bootstrap モーダルを表示:
   - タイトル: 「メール通知」
   - 本文: 「{提出者名} に更新内容をメールで通知しますか？」
   - ボタン1: 「通知して保存」→ `notify_submitter=1` の hidden input を追加して送信
   - ボタン2: 「通知せずに保存」→ `notify_submitter=0` で送信
3. `is_admin=True` のときのみモーダルを有効化（Django テンプレートの `{% if is_admin %}` で制御）

---

## バックエンド設計

### 変更ファイル
- `expenses/views.py`

### `feedback_edit` ビューの変更

POST 処理の `fb.save()` の後に以下を追加:

```python
if is_admin and request.POST.get('notify_submitter') == '1':
    _feedback_notify_submitter(fb, request.user)
```

### 新規関数 `_feedback_notify_submitter(fb, updater)`

```python
def _feedback_notify_submitter(fb, updater):
    from .utils import send_notification
    submitter = fb.man_number
    if not submitter or not getattr(submitter, 'email', None):
        return
    status_label = dict(T_Feedback.STATUS_CHOICES).get(fb.status_cd, fb.status_cd)
    subject = f'【改善要望】#{fb.feedback_id} 状況が更新されました'
    message = (
        f'あなたの改善要望が更新されました。\n\n'
        f'要望ID : #{fb.feedback_id}\n'
        f'状況   : {status_label}\n'
        f'回答   : {fb.response_text or "（未回答）"}\n'
        f'更新日 : {fb.updated_at}\n'
        f'更新者 : {getattr(updater, "user_name", updater)}\n\n'
        f'詳細はシステムからご確認ください。'
    )
    send_notification(submitter.email, subject, message)
```

---

## データフロー

```
管理者が保存ボタンクリック
    → JS がフォーム送信を一時停止
    → Bootstrap モーダル表示
    → 管理者が「通知して保存」or「通知せずに保存」を選択
    → hidden input notify_submitter = 1 or 0 をセットして POST 送信
    → feedback_edit ビューが保存処理
    → notify_submitter == '1' なら _feedback_notify_submitter() 呼び出し
    → send_notification() で提出者へメール送信
```

---

## エラーハンドリング

- 提出者のメールアドレスが未設定の場合は通知をスキップ（ログなし）
- `send_notification()` 内で例外は catch してサーバーログへ出力（既存動作）

---

## テスト観点

- 管理者編集時に保存ボタンを押すとモーダルが表示される
- 「通知して保存」でメールが送信される
- 「通知せずに保存」でメールが送信されない
- 提出者自身が編集する場合はモーダルが表示されない
- 提出者のメールアドレスが空の場合は通知なしで正常保存される

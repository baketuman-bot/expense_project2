# 改善要望 更新時提出者メール通知 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 管理者が改善要望を編集保存する際に、提出者へのメール通知可否を確認モーダルで選択できるようにする。

**Architecture:** `feedback_edit` ビューに `notify_submitter` POST パラメータを追加し、`1` の場合に `_feedback_notify_submitter()` を呼び出す。フロントエンドでは Bootstrap モーダルを表示して管理者に通知可否を選ばせ、選択結果を hidden input でフォーム送信する。

**Tech Stack:** Django 5.2, Bootstrap 5 (モーダル), JavaScript (vanilla), Django Test Client, unittest.mock

---

## 変更ファイル一覧

| ファイル | 変更種別 | 内容 |
|---|---|---|
| `expenses/views.py` | 修正 | `_feedback_notify_submitter()` 追加、`feedback_edit` に通知送信ロジック追加 |
| `expenses/templates/expenses/feedback_form.html` | 修正 | 通知確認モーダル・hidden input・JS 追加 |
| `expenses/tests.py` | 修正 | `_feedback_notify_submitter` と `feedback_edit` の通知フラグテスト追加 |

---

## Task 1: バックエンド — 通知関数と `feedback_edit` の更新

**Files:**
- Modify: `expenses/views.py` (関数 `_feedback_notify_superusers` の直後、約 4296行目付近)

### 背景

`expenses/views.py` の `_feedback_notify_superusers()` は 4282行目付近にある。その直後（4297行目付近、`@login_required` デコレータの前）に新しい `_feedback_notify_submitter()` を追加する。

`feedback_edit` ビューは 4307行目付近。POST 処理内の `fb.save()` の直後、`return redirect(...)` の前に通知ロジックを追加する。

`T_Feedback` は `feedback_edit` ビュー内で `from .models import T_Feedback` としてインポート済み。

### Steps

- [ ] **Step 1: `_feedback_notify_submitter()` 関数を追加する**

`expenses/views.py` の `_feedback_notify_superusers` 定義の直後（`@login_required` の前の空行）に以下を挿入する:

```python
def _feedback_notify_submitter(fb, updater):
    from .utils import send_notification
    submitter = fb.man_number
    if not submitter or not getattr(submitter, 'email', None):
        return
    status_label = dict(T_Feedback.STATUS_CHOICES).get(fb.status_cd, fb.status_cd)
    subject = '【改善要望】#' + str(fb.feedback_id) + ' 状況が更新されました'
    message = (
        'あなたの改善要望が更新されました。\n\n'
        '要望ID : #' + str(fb.feedback_id) + '\n'
        '状況   : ' + status_label + '\n'
        '回答   : ' + (fb.response_text or '（未回答）') + '\n'
        '更新日 : ' + str(fb.updated_at) + '\n'
        '更新者 : ' + str(getattr(updater, 'user_name', updater)) + '\n\n'
        '詳細はシステムからご確認ください。'
    )
    send_notification(submitter.email, subject, message)
```

- [ ] **Step 2: `feedback_edit` ビューの POST 処理に通知ロジックを追加する**

`feedback_edit` の POST 処理内、`fb.save()` の直後・`return redirect(...)` の直前を以下のように変更する。

変更前:
```python
        fb.save()
        return redirect('expenses:feedback_detail', pk=fb.pk)
```

変更後:
```python
        fb.save()
        if is_admin and request.POST.get('notify_submitter') == '1':
            _feedback_notify_submitter(fb, request.user)
        return redirect('expenses:feedback_detail', pk=fb.pk)
```

- [ ] **Step 3: コミット**

```bash
git add expenses/views.py
git commit -m "feat: 改善要望 更新時提出者メール通知関数を追加"
```

---

## Task 2: テスト — バックエンド通知ロジックの検証

**Files:**
- Modify: `expenses/tests.py`

### 背景

`expenses/tests.py` には既存テストクラスがある。末尾に `FeedbackNotifySubmitterTest` クラスを追加する。

テストの方針:
- `_feedback_notify_submitter()` が `send_notification` を正しい引数で呼ぶことを `patch` で検証
- `feedback_edit` に `notify_submitter=1` を POST すると通知が送られることを検証
- `feedback_edit` に `notify_submitter=0` を POST すると通知が送られないことを検証

### 必要なフィクスチャの準備

テスト内で以下のオブジェクトを `setUp` で作成する:
- `M_User` (提出者): `man_number='U001'`, `user_name='提出者A'`, `email='submitter@example.com'`
- `M_User` (管理者): `man_number='A001'`, `user_name='管理者B'`, `email='admin@example.com'`
- `M_UserRole`: `man_number='A001'`, `role='admin'`
- `T_Feedback`: `man_number=提出者`, `request_text='テスト要望'`, `status_cd='00'`

`M_User` は `AbstractUser` ベースのカスタムモデル。`create_user` の必須フィールドは `username`, `man_number`, `user_name`, `password`。

### Steps

- [ ] **Step 1: テストクラスと setUp を追加する**

`expenses/tests.py` 末尾に追加:

```python
class FeedbackNotifySubmitterTest(TestCase):
    """改善要望 更新時の提出者メール通知テスト"""

    def setUp(self):
        from django.contrib.auth import get_user_model
        from expenses.models import T_Feedback, M_UserRole
        User = get_user_model()

        self.submitter = User.objects.create_user(
            username='submitter_u001',
            man_number='U001',
            user_name='提出者A',
            password='pass123',
            email='submitter@example.com',
        )
        self.admin_user = User.objects.create_user(
            username='admin_a001',
            man_number='A001',
            user_name='管理者B',
            password='pass123',
            email='admin@example.com',
        )
        M_UserRole.objects.create(man_number=self.admin_user, role='admin')

        self.fb = T_Feedback.objects.create(
            man_number=self.submitter,
            request_text='テスト要望',
            status_cd='00',
        )
        self.client = Client()
```

- [ ] **Step 2: テスト失敗を確認する**

```bash
cd /home/idc_user/expense_project2
python manage.py test expenses.tests.FeedbackNotifySubmitterTest --keepdb 2>&1 | tail -20
```

Expected: `ImportError` または `NameError`（まだテストメソッドがないためエラーになる可能性あり）。setUp が通ることを確認。

- [ ] **Step 3: `_feedback_notify_submitter` の単体テストを追加する**

上記クラスに以下のメソッドを追加:

```python
    def test_notify_submitter_sends_email(self):
        """_feedback_notify_submitter は提出者のメールアドレスへ send_notification を呼ぶ"""
        from expenses.views import _feedback_notify_submitter
        with patch('expenses.views.send_notification') as mock_send:
            _feedback_notify_submitter(self.fb, self.admin_user)
        mock_send.assert_called_once()
        call_args = mock_send.call_args[0]
        self.assertEqual(call_args[0], 'submitter@example.com')
        self.assertIn(str(self.fb.feedback_id), call_args[1])
        self.assertIn('提出者A', call_args[2])  # 本文に提出者名は不要だが更新者名が含まれる
        self.assertIn('管理者B', call_args[2])

    def test_notify_submitter_skips_if_no_email(self):
        """提出者のメールアドレスが空の場合は send_notification を呼ばない"""
        from expenses.views import _feedback_notify_submitter
        self.submitter.email = ''
        self.submitter.save()
        with patch('expenses.views.send_notification') as mock_send:
            _feedback_notify_submitter(self.fb, self.admin_user)
        mock_send.assert_not_called()

    def test_feedback_edit_with_notify_sends_email(self):
        """feedback_edit に notify_submitter=1 を POST すると提出者に通知される"""
        self.client.force_login(self.admin_user)
        with patch('expenses.views.send_notification') as mock_send:
            response = self.client.post(
                f'/feedback/{self.fb.pk}/edit/',
                {
                    'request_text': 'テスト要望',
                    'response_text': '対応しました',
                    'status_cd': '02',
                    'notify_submitter': '1',
                },
            )
        self.assertEqual(response.status_code, 302)
        mock_send.assert_called_once()
        self.assertEqual(mock_send.call_args[0][0], 'submitter@example.com')

    def test_feedback_edit_without_notify_skips_email(self):
        """feedback_edit に notify_submitter=0 を POST すると通知されない"""
        self.client.force_login(self.admin_user)
        with patch('expenses.views.send_notification') as mock_send:
            response = self.client.post(
                f'/feedback/{self.fb.pk}/edit/',
                {
                    'request_text': 'テスト要望',
                    'response_text': '対応しました',
                    'status_cd': '02',
                    'notify_submitter': '0',
                },
            )
        self.assertEqual(response.status_code, 302)
        mock_send.assert_not_called()
```

- [ ] **Step 4: テストを実行して全件パスを確認する**

```bash
cd /home/idc_user/expense_project2
python manage.py test expenses.tests.FeedbackNotifySubmitterTest --keepdb 2>&1 | tail -20
```

Expected: `OK (4 tests)`

- [ ] **Step 5: コミット**

```bash
git add expenses/tests.py
git commit -m "test: 改善要望 提出者メール通知のテストを追加"
```

---

## Task 3: フロントエンド — 通知確認モーダルと JS

**Files:**
- Modify: `expenses/templates/expenses/feedback_form.html`

### 背景

`feedback_form.html` の現在の構成:
- `<form method="post">` (31行目): メインフォーム（ID なし）
- 保存ボタン (61行目): `type="submit"`
- 削除フォーム (66行目): メインフォーム内の別フォーム要素
- `{% block extra_js %}` (81行目): 削除確認の JS がある

### 変更内容

1. メインフォームに `id="feedback-main-form"` を追加
2. フォーム内（`{% csrf_token %}` 直後）に hidden input を追加:  
   `<input type="hidden" name="notify_submitter" id="notify-submitter-input" value="0">`
3. `{% endblock %}` の前（コンテンツブロック末尾）にモーダル HTML を追加（`is_admin and mode == 'edit'` 条件付き）
4. `{% block extra_js %}` の JS にモーダル制御を追加

### Steps

- [ ] **Step 1: メインフォームに ID を付与し、hidden input を追加する**

31行目の `<form method="post">` を以下に変更:

```html
            <form method="post" id="feedback-main-form">
                {% csrf_token %}
                <input type="hidden" name="notify_submitter" id="notify-submitter-input" value="0">
```

- [ ] **Step 2: 通知確認モーダルを追加する**

`</div>` (78行目、コンテンツ末尾の閉じタグ) の直前に追加:

```html
{% if is_admin and mode == 'edit' %}
<div class="modal fade" id="notifyModal" tabindex="-1" aria-labelledby="notifyModalLabel" aria-hidden="true">
    <div class="modal-dialog">
        <div class="modal-content">
            <div class="modal-header">
                <h5 class="modal-title" id="notifyModalLabel">
                    <i class="fas fa-envelope me-2 text-primary"></i>メール通知
                </h5>
                <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
            </div>
            <div class="modal-body">
                {% if fb.man_number %}<strong>{{ fb.man_number.user_name }}</strong> さん{% else %}提出者{% endif %}に更新内容をメールで通知しますか？
            </div>
            <div class="modal-footer">
                <button type="button" class="btn btn-outline-secondary" id="btn-notify-no">
                    通知せずに保存
                </button>
                <button type="button" class="btn btn-primary" id="btn-notify-yes">
                    <i class="fas fa-envelope me-1"></i>通知して保存
                </button>
            </div>
        </div>
    </div>
</div>
{% endif %}
```

- [ ] **Step 3: JS にモーダル制御を追加する**

`{% block extra_js %}` の `<script>` 内、既存コード（削除確認）の後に以下を追加:

```javascript
{% if is_admin and mode == 'edit' %}
(function () {
    var mainForm = document.getElementById('feedback-main-form');
    var notifyInput = document.getElementById('notify-submitter-input');
    var modalEl = document.getElementById('notifyModal');
    var notifyModal = new bootstrap.Modal(modalEl);

    mainForm.addEventListener('submit', function (e) {
        e.preventDefault();
        notifyModal.show();
    });

    document.getElementById('btn-notify-yes').addEventListener('click', function () {
        notifyInput.value = '1';
        notifyModal.hide();
        mainForm.submit();
    });

    document.getElementById('btn-notify-no').addEventListener('click', function () {
        notifyInput.value = '0';
        notifyModal.hide();
        mainForm.submit();
    });
}());
{% endif %}
```

- [ ] **Step 4: 動作確認**

開発サーバーを起動して手動で確認する:

```bash
cd /home/idc_user/expense_project2
python manage.py runserver
```

確認手順:
1. adminロールのユーザーでログインして `/feedback/<id>/edit/` を開く
2. 更新ボタンを押すとモーダルが表示されること
3. 「通知して保存」でリダイレクト後、サーバーログにメール送信ログが出ること（メール設定によっては `[mail][WARN]` または `[mail][ERROR]`）
4. 「通知せずに保存」でメールログが出ないこと
5. 管理者でないユーザーで編集画面を開き、モーダルが表示されず直接保存されること

- [ ] **Step 5: コミット**

```bash
git add expenses/templates/expenses/feedback_form.html
git commit -m "feat: 改善要望編集画面に提出者通知確認モーダルを追加"
```

---

## 完了チェック

- [ ] `python manage.py test expenses.tests.FeedbackNotifySubmitterTest --keepdb` が全件パス
- [ ] `python manage.py test expenses --keepdb` で既存テストが壊れていないこと
- [ ] 管理者ユーザーで編集画面を開くとモーダルが表示される
- [ ] 非管理者ユーザーでモーダルが表示されない

from django import forms
from django.forms import modelformset_factory
from .models import T_Document, T_DocumentContent


class MultiFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True

class MultiFileField(forms.Field):
    widget = MultiFileInput

    def __init__(self, *args, **kwargs):
        # デフォルトで必須にしない（添付任意）
        kwargs.setdefault('required', False)
        super().__init__(*args, **kwargs)

    def to_python(self, data):
        # ファイル未選択時は None/空文字/空リストを None 扱い
        if data in (None, ""):
            return None
        return data  # list[UploadedFile] or UploadedFile をそのまま

    def validate(self, value):
        # 必須時のみ検証
        if self.required and not value:
            raise forms.ValidationError("このフィールドは必須です。")

# ExpenseFormは削除 - 合計金額は自動計算するため不要

class ExpenseDetailForm(forms.ModelForm):
    date = forms.DateField(
        label="日付",
        widget=forms.DateInput(attrs={
            'type': 'date',
            'class': 'form-control',
            'placeholder': 'YYYY-MM-DD'
        })
    )
    # モデルから領収書フィールドを削除したため、非モデルの FileField として保持
    receipt = MultiFileField(
        label="領収書",
        required=False,
        widget=MultiFileInput(attrs={'multiple': True})
    )

    class Meta:
        model = T_DocumentContent
        fields = ["date", "amount", "purpose", "shiharaisaki", "account", "tekikaku_cd"]
        labels = {
            "amount": "金額（円）",
            "purpose": "目的",
            "shiharaisaki": "取引先",
            "account": "勘定科目",
            "tekikaku_cd": "登録番号",
        }

    def clean_amount(self):
        amount = self.cleaned_data["amount"]
        if amount <= 0:
            raise forms.ValidationError("金額は0より大きい値を入力してください。")
        return amount

ExpenseDetailFormSet = modelformset_factory(
    T_DocumentContent,
    form=ExpenseDetailForm,
    extra=1,
    can_delete=False,
    validate_min=False,
    min_num=0,
    validate_max=True,
    max_num=10
)

# 編集用（余計な空フォームを出さない）
ExpenseDetailEditFormSet = modelformset_factory(
    T_DocumentContent,
    form=ExpenseDetailForm,
    extra=0,
    can_delete=False,
    validate_min=False,
    min_num=0,
    validate_max=True,
    max_num=10
)

class ApprovalForm(forms.Form):
    # 指定のコード体系に合わせる
    STATUS_CHOICES = [
        ("APP", "承認"),   # 回覧中（承認アクション）
        ("REJ", "却下"),
        ("RET", "差戻し"),
    ]
    status = forms.ChoiceField(choices=STATUS_CHOICES)
    comment = forms.CharField(widget=forms.Textarea, required=False)

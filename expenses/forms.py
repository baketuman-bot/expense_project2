from django import forms
from django.forms import modelformset_factory, BaseModelFormSet
from .models import T_Document, T_DocumentContent, M_Account


class CommaDecimalField(forms.DecimalField):
    """カンマ区切り入力（例: "1,234"）を受け付けるDecimalField。"""
    def to_python(self, value):
        if value not in (None, ''):
            value = str(value).replace(',', '')
        return super().to_python(value)


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
        label="取引日",
        required=False,
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

    # Cloud Storage(スマホアップロード)の領収書を取り込むための入力欄（後方互換用・非表示）
    cloud_receipts = forms.CharField(
        label="Cloud領収書（連番）",
        required=False,
        widget=forms.HiddenInput(),
    )

    # モバイルQRアップロードID（フォームごとに独立して管理）
    mobile_upload_id = forms.CharField(
        required=False,
        widget=forms.HiddenInput(),
    )

    CORPO_CARD_CHOICES = [
        ('', '選択してください'),
        (1, 'その他'),
        (2, 'コーポレートカード支払い'),
    ]
    corpo_card = forms.TypedChoiceField(
        label="コーポレートカード支払い",
        required=False,
        choices=CORPO_CARD_CHOICES,
        coerce=int,
        empty_value=None,
        initial=1,
        widget=forms.Select(attrs={'class': 'form-select', 'data-corpo-card-select': ''}),
    )

    corpo_card_no = forms.CharField(
        label="カード番号",
        required=False,
        max_length=10,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'カード番号（下4桁等）',
            'data-corpo-card-no': '',
        }),
    )

    class Meta:
        model = T_DocumentContent
        fields = ["date", "amount", "purpose", "shiharaisaki", "account", "tekikaku_cd", "corpo_card", "corpo_card_no"]
        labels = {
            "amount": "金額",
            "purpose": "目的",
            "shiharaisaki": "支払先",
            "account": "勘定科目",
            "tekikaku_cd": "登録番号",
        }
        widgets = {
            'amount': forms.TextInput(attrs={
                'class': 'form-control',
                'inputmode': 'numeric',
                'placeholder': '0',
                'data-amount-input': '',
                'autocomplete': 'off',
            }),
        }

    def __init__(self, *args, account_queryset=None, is_draft=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.is_draft = is_draft
        if account_queryset is not None:
            self.fields['account'].queryset = account_queryset
        self.fields['amount'] = CommaDecimalField(
            required=False, max_digits=10, decimal_places=2,
            label='金額',
            widget=forms.TextInput(attrs={
                'class': 'form-control',
                'inputmode': 'numeric',
                'placeholder': '0',
                'data-amount-input': '',
                'autocomplete': 'off',
            }),
        )

    def clean_amount(self):
        amount = self.cleaned_data.get("amount")
        # 下書き保存・空行は許容（申請時の必須チェックは view 側で行う）
        if amount in (None, ''):
            return amount
        if amount <= 0:
            raise forms.ValidationError("金額は0より大きい値を入力してください。")
        return amount

    def clean(self):
        cleaned = super().clean()
        corpo_card = cleaned.get("corpo_card")
        corpo_card_no = (cleaned.get("corpo_card_no") or "").strip()
        # コーポレートカード支払い選択時はカード番号必須（下書き時はスキップ）
        if not self.is_draft and corpo_card == 2 and not corpo_card_no:
            self.add_error("corpo_card_no", "コーポレートカード支払いを選択した場合、カード番号を入力してください。")
        return cleaned


class BaseExpenseDetailFormSet(BaseModelFormSet):
    """account_queryset / is_draft をフォームセット経由で各フォームに渡すための基底クラス"""
    def __init__(self, *args, account_queryset=None, is_draft=False, **kwargs):
        self.account_queryset = account_queryset
        self.is_draft = is_draft
        super().__init__(*args, **kwargs)

    def _construct_form(self, i, **kwargs):
        if self.account_queryset is not None:
            kwargs['account_queryset'] = self.account_queryset
        kwargs['is_draft'] = self.is_draft
        return super()._construct_form(i, **kwargs)


ExpenseDetailFormSet = modelformset_factory(
    T_DocumentContent,
    form=ExpenseDetailForm,
    formset=BaseExpenseDetailFormSet,
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
    formset=BaseExpenseDetailFormSet,
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
        ("APPROVED", "承認"),   # 回覧中（承認アクション）
        ("REJECTED", "却下"),
        ("RETURNED", "差戻し"),
    ]
    status = forms.ChoiceField(choices=STATUS_CHOICES)
    comment = forms.CharField(widget=forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}), required=False)


# ─── 出張旅費精算 (DocType=5) 用フォーム ───────────────────────────────────

TRANSPORT_CHOICES = [
    ('', '-- 選択 --'),
    ('新幹線', '新幹線'),
    ('在来線', '在来線'),
    ('特急', '特急'),
    ('バス', 'バス'),
    ('タクシー', 'タクシー'),
    ('飛行機', '飛行機'),
    ('船', '船'),
    ('自家用車', '自家用車'),
    ('レンタカー', 'レンタカー'),
    ('その他', 'その他'),
]

TEKIKAKU_CHOICES = [('有', '有'), ('無', '無')]


class TravelDetailForm(forms.ModelForm):
    """出張旅費精算の1経路行を表すフォーム。
    経路固有フィールド（発地・着地・交通手段・所要時間・適格番号有無）は
    T_DocumentContent.content (JSONField) に保存する。
    経費明細フィールド（支払先・登録番号・コーポレートカード・領収書等）も
    同一レコードに保存する。
    """

    date = forms.DateField(
        label="日付",
        required=False,
        widget=forms.DateInput(attrs={
            'type': 'date',
            'class': 'form-control form-control-sm',
        })
    )
    departure = forms.CharField(
        label="発地",
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control form-control-sm',
            'placeholder': '発地',
        })
    )
    arrival = forms.CharField(
        label="着地",
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control form-control-sm',
            'placeholder': '着地',
        })
    )
    transport = forms.ChoiceField(
        label="交通手段",
        choices=TRANSPORT_CHOICES,
        required=False,
        widget=forms.Select(attrs={'class': 'form-select form-select-sm'})
    )
    duration = forms.CharField(
        label="所要時間",
        required=False,
        max_length=20,
        widget=forms.TextInput(attrs={
            'class': 'form-control form-control-sm',
            'placeholder': '例: 2:30',
        })
    )
    tekikaku_flag = forms.ChoiceField(
        label="適格番号",
        choices=TEKIKAKU_CHOICES,
        required=False,
        initial='無',
        widget=forms.Select(attrs={'class': 'form-select form-select-sm'})
    )

    # ── 経費明細フィールド（同一レコードに保存） ──────────────────────────
    receipt = MultiFileField(
        label="領収書",
        required=False,
        widget=MultiFileInput(attrs={
            'multiple': True,
            'class': 'form-control file-input d-none',
            'accept': 'image/*,.pdf',
        })
    )
    cloud_receipts = forms.CharField(
        label="Cloud領収書（連番）",
        required=False,
        widget=forms.HiddenInput(),
    )
    mobile_upload_id = forms.CharField(
        required=False,
        widget=forms.HiddenInput(),
    )

    CORPO_CARD_CHOICES = [
        ('', '選択してください'),
        (1, 'その他'),
        (2, 'コーポレートカード支払い'),
    ]
    corpo_card = forms.TypedChoiceField(
        label="コーポレートカード支払い",
        required=False,
        choices=CORPO_CARD_CHOICES,
        coerce=int,
        empty_value=None,
        initial=1,
        widget=forms.Select(attrs={'class': 'form-select form-select-sm', 'data-corpo-card-select': ''}),
    )
    corpo_card_no = forms.CharField(
        label="カード番号",
        required=False,
        max_length=10,
        widget=forms.TextInput(attrs={
            'class': 'form-control form-control-sm',
            'placeholder': 'カード番号（下4桁等）',
            'data-corpo-card-no': '',
        }),
    )

    class Meta:
        model = T_DocumentContent
        fields = ['date', 'amount', 'shiharaisaki', 'tekikaku_cd', 'corpo_card', 'corpo_card_no']
        labels = {
            'amount': '運賃(円)',
            'shiharaisaki': '支払先',
            'tekikaku_cd': '登録番号',
        }
        widgets = {
            'amount': forms.TextInput(attrs={
                'class': 'form-control form-control-sm',
                'inputmode': 'numeric',
                'placeholder': '0',
                'data-amount-input': '',
                'autocomplete': 'off',
            }),
            'shiharaisaki': forms.TextInput(attrs={
                'class': 'form-control form-control-sm',
                'placeholder': '例: JR東日本',
            }),
            'tekikaku_cd': forms.TextInput(attrs={
                'class': 'form-control form-control-sm',
                'placeholder': '登録番号',
            }),
        }

    def __init__(self, *args, is_draft=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.is_draft = is_draft
        self.fields['amount'] = CommaDecimalField(
            required=False, max_digits=10, decimal_places=2,
            label='運賃(円)',
            widget=forms.TextInput(attrs={
                'class': 'form-control form-control-sm',
                'inputmode': 'numeric',
                'placeholder': '0',
                'data-amount-input': '',
                'autocomplete': 'off',
            }),
        )
        self.fields['shiharaisaki'].required = False
        self.fields['tekikaku_cd'].required = False
        self.fields['corpo_card'].required = False
        self.fields['corpo_card_no'].required = False
        # 既存インスタンスの content JSON から各フィールドの初期値を復元
        if self.instance and self.instance.pk and isinstance(self.instance.content, dict):
            c = self.instance.content
            self.initial.update({
                'departure':     c.get('departure', ''),
                'arrival':       c.get('arrival', ''),
                'transport':     c.get('transport', ''),
                'duration':      c.get('duration', ''),
                'tekikaku_flag': c.get('tekikaku_flag', '無'),
            })

    def clean(self):
        cleaned = super().clean()
        corpo_card = cleaned.get("corpo_card")
        corpo_card_no = (cleaned.get("corpo_card_no") or "").strip()
        # コーポレートカード支払い選択時はカード番号必須（下書き時はスキップ）
        if not self.is_draft and corpo_card == 2 and not corpo_card_no:
            self.add_error("corpo_card_no", "コーポレートカード支払いを選択した場合、カード番号を入力してください。")
        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.content = {
            'departure':     self.cleaned_data.get('departure', ''),
            'arrival':       self.cleaned_data.get('arrival', ''),
            'transport':     self.cleaned_data.get('transport', ''),
            'duration':      self.cleaned_data.get('duration', ''),
            'tekikaku_flag': self.cleaned_data.get('tekikaku_flag') or '無',
        }
        if commit:
            instance.save()
        return instance


class BaseTravelDetailFormSet(BaseModelFormSet):
    """is_draft をフォームセット経由で TravelDetailForm に渡すための基底クラス"""
    def __init__(self, *args, is_draft=False, **kwargs):
        self.is_draft = is_draft
        super().__init__(*args, **kwargs)

    def _construct_form(self, i, **kwargs):
        kwargs['is_draft'] = self.is_draft
        return super()._construct_form(i, **kwargs)


TravelDetailFormSet = modelformset_factory(
    T_DocumentContent,
    form=TravelDetailForm,
    formset=BaseTravelDetailFormSet,
    extra=1,
    can_delete=False,
    validate_min=False,
    min_num=0,
    validate_max=True,
    max_num=30,
)

TravelDetailEditFormSet = modelformset_factory(
    T_DocumentContent,
    form=TravelDetailForm,
    formset=BaseTravelDetailFormSet,
    extra=0,
    can_delete=False,
    validate_min=False,
    min_num=0,
    validate_max=True,
    max_num=30,
)


# ─── 宿泊費 (DocType=5) ───────────────────────────────────────────────────────

class AccommodationForm(forms.ModelForm):
    date = forms.DateField(
        label='日付',
        required=False,
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control form-control-sm'}),
    )
    nights = forms.IntegerField(
        label='宿泊日数',
        required=False,
        min_value=1,
        widget=forms.NumberInput(attrs={
            'class': 'form-control form-control-sm',
            'placeholder': '1',
            'min': '1',
        }),
    )
    receipt = MultiFileField(
        label='領収書',
        required=False,
        widget=MultiFileInput(attrs={
            'multiple': True,
            'class': 'form-control file-input d-none',
            'accept': 'image/*,.pdf',
        }),
    )
    cloud_receipts = forms.CharField(label='Cloud領収書', required=False, widget=forms.HiddenInput())
    mobile_upload_id = forms.CharField(required=False, widget=forms.HiddenInput())

    CORPO_CARD_CHOICES = [
        ('', '選択してください'),
        (1, 'その他'),
        (2, 'コーポレートカード支払い'),
    ]
    corpo_card = forms.TypedChoiceField(
        label='コーポレートカード支払い',
        required=False,
        choices=CORPO_CARD_CHOICES,
        coerce=int,
        empty_value=None,
        initial=1,
        widget=forms.Select(attrs={'class': 'form-select form-select-sm', 'data-corpo-card-select': ''}),
    )
    corpo_card_no = forms.CharField(
        label='カード番号',
        required=False,
        max_length=10,
        widget=forms.TextInput(attrs={
            'class': 'form-control form-control-sm',
            'placeholder': 'カード番号（下4桁等）',
            'data-corpo-card-no': '',
        }),
    )

    class Meta:
        model = T_DocumentContent
        fields = ['date', 'amount', 'shiharaisaki', 'tekikaku_cd', 'corpo_card', 'corpo_card_no']
        labels = {'amount': '金額', 'shiharaisaki': '支払先', 'tekikaku_cd': '登録番号'}
        widgets = {
            'shiharaisaki': forms.TextInput(attrs={'class': 'form-control form-control-sm', 'placeholder': '例: ○○ホテル'}),
            'tekikaku_cd': forms.TextInput(attrs={'class': 'form-control form-control-sm', 'placeholder': '登録番号'}),
        }

    def __init__(self, *args, is_draft=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.is_draft = is_draft
        self.fields['amount'] = CommaDecimalField(
            required=False, max_digits=10, decimal_places=2,
            label='金額',
            widget=forms.TextInput(attrs={
                'class': 'form-control form-control-sm',
                'inputmode': 'numeric',
                'placeholder': '0',
                'data-amount-input': '',
                'autocomplete': 'off',
            }),
        )
        self.fields['shiharaisaki'].required = False
        self.fields['tekikaku_cd'].required = False
        if self.instance and self.instance.pk and isinstance(self.instance.content, dict):
            c = self.instance.content
            self.initial['nights'] = c.get('nights', '')

    def clean(self):
        cleaned = super().clean()
        corpo_card = cleaned.get('corpo_card')
        corpo_card_no = (cleaned.get('corpo_card_no') or '').strip()
        # コーポレートカード支払い選択時はカード番号必須（下書き時はスキップ）
        if not self.is_draft and corpo_card == 2 and not corpo_card_no:
            self.add_error('corpo_card_no', 'コーポレートカード支払いを選択した場合、カード番号を入力してください。')
        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.content = {
            'row_type': 'accommodation',
            'nights': self.cleaned_data.get('nights') or '',
        }
        if commit:
            instance.save()
        return instance


class BaseAccommodationFormSet(BaseModelFormSet):
    """is_draft をフォームセット経由で AccommodationForm に渡すための基底クラス"""
    def __init__(self, *args, is_draft=False, **kwargs):
        self.is_draft = is_draft
        super().__init__(*args, **kwargs)

    def _construct_form(self, i, **kwargs):
        kwargs['is_draft'] = self.is_draft
        return super()._construct_form(i, **kwargs)


AccommodationFormSet = modelformset_factory(
    T_DocumentContent,
    form=AccommodationForm,
    formset=BaseAccommodationFormSet,
    extra=1,
    can_delete=False,
    validate_min=False,
    min_num=0,
    validate_max=True,
    max_num=10,
)

AccommodationEditFormSet = modelformset_factory(
    T_DocumentContent,
    form=AccommodationForm,
    formset=BaseAccommodationFormSet,
    extra=0,
    can_delete=False,
    validate_min=False,
    min_num=0,
    validate_max=True,
    max_num=10,
)


# ─── 日当 (DocType=5) ─────────────────────────────────────────────────────────

class AllowanceForm(forms.ModelForm):
    unit_price_key = forms.ChoiceField(
        label='単価',
        required=False,
        choices=[('', '-- 選択 --')],
        widget=forms.Select(attrs={'class': 'form-select form-select-sm', 'data-allowance-unit-price': ''}),
    )
    days = forms.IntegerField(
        label='日数',
        required=False,
        min_value=1,
        widget=forms.NumberInput(attrs={
            'class': 'form-control form-control-sm',
            'placeholder': '1',
            'min': '1',
            'data-allowance-days': '',
        }),
    )

    class Meta:
        model = T_DocumentContent
        fields = ['amount']
        labels = {'amount': '金額（円）'}
        widgets = {
            'amount': forms.TextInput(attrs={
                'class': 'form-control form-control-sm',
                'inputmode': 'numeric',
                'placeholder': '自動計算',
                'data-amount-input': '',
                'data-allowance-amount': '',
                'readonly': 'readonly',
                'autocomplete': 'off',
            }),
        }

    def __init__(self, *args, tra_items=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['amount'] = CommaDecimalField(
            required=False, max_digits=10, decimal_places=2,
            label='金額（円）',
            widget=forms.TextInput(attrs={
                'class': 'form-control form-control-sm',
                'inputmode': 'numeric',
                'placeholder': '自動計算',
                'data-amount-input': '',
                'data-allowance-amount': '',
                'readonly': 'readonly',
                'autocomplete': 'off',
            }),
        )
        if tra_items is not None:
            self.fields['unit_price_key'].choices = (
                [('', '-- 選択 --')] +
                [(item.key, item.content2) for item in tra_items]
            )
        if self.instance and self.instance.pk and isinstance(self.instance.content, dict):
            c = self.instance.content
            self.initial.update({
                'unit_price_key': c.get('unit_price_key', ''),
                'days': c.get('days', ''),
            })

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.content = {
            'row_type': 'allowance',
            'unit_price_key': self.cleaned_data.get('unit_price_key') or '',
            'days': self.cleaned_data.get('days') or '',
        }
        if commit:
            instance.save()
        return instance


class BaseAllowanceFormSet(BaseModelFormSet):
    def __init__(self, *args, tra_items=None, **kwargs):
        self.tra_items = tra_items
        super().__init__(*args, **kwargs)

    def _construct_form(self, i, **kwargs):
        if self.tra_items is not None:
            kwargs['tra_items'] = self.tra_items
        return super()._construct_form(i, **kwargs)


AllowanceFormSet = modelformset_factory(
    T_DocumentContent,
    form=AllowanceForm,
    formset=BaseAllowanceFormSet,
    extra=1,
    can_delete=False,
    validate_min=False,
    min_num=0,
    validate_max=True,
    max_num=10,
)

AllowanceEditFormSet = modelformset_factory(
    T_DocumentContent,
    form=AllowanceForm,
    formset=BaseAllowanceFormSet,
    extra=0,
    can_delete=False,
    validate_min=False,
    min_num=0,
    validate_max=True,
    max_num=10,
)

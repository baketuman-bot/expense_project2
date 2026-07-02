from django import forms
from django.forms import modelformset_factory, BaseModelFormSet
from .models import T_Document, T_DocumentContent, M_Account, M_Item, T_Assets


def _get_item_choices(data_kbn, empty_label='選択してください', fallback=None):
    """M_Itemからプルダウン選択肢を生成。データがなければfallbackを返す。
    全角数字は半角に正規化（IntegerFieldへの保存に対応）。"""
    import unicodedata
    items = list(M_Item.objects.filter(data_kbn=data_kbn).order_by('key').values_list('key', 'content'))
    if items:
        normalized = [(unicodedata.normalize('NFKC', k), v) for k, v in items]
        return [('', empty_label)] + normalized
    return fallback or [('', empty_label)]


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
        (1, '不使用'),
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

    CONSUMPTION_KBN_CHOICES = [
        ('', '--'),
        (0, '内税'),
        (1, '外税'),
    ]
    # 内税をデフォルト選択
    consumption_kbn = forms.TypedChoiceField(
        label="内外税区分",
        required=False,
        choices=CONSUMPTION_KBN_CHOICES,
        coerce=lambda x: int(x) if x != '' else None,
        empty_value=None,
        initial=0,
        widget=forms.Select(attrs={'class': 'form-select'}),
    )

    class Meta:
        model = T_DocumentContent
        fields = ["date", "amount", "purpose", "shiharaisaki", "account", "tekikaku_cd", "corpo_card", "corpo_card_no", "consumption_kbn", "consumption_tax"]
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
        self.fields['consumption_tax'] = CommaDecimalField(
            required=False, max_digits=10, decimal_places=2,
            label='消費税額',
            widget=forms.TextInput(attrs={
                'class': 'form-control',
                'inputmode': 'numeric',
                'placeholder': '0',
                'data-amount-input': '',
                'autocomplete': 'off',
            }),
        )
        self.fields['corpo_card'].choices = _get_item_choices(
            'COC',
            fallback=[('', '選択してください'), ('1', '不使用'), ('2', 'コーポレートカード支払い')],
        )
        self.fields['consumption_kbn'].choices = _get_item_choices(
            'TAX',
            empty_label='--',
            fallback=[('', '--'), ('0', '内税'), ('1', '外税')],
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
        # 外税選択時は消費税額必須（下書き時はスキップ）
        if not self.is_draft and cleaned.get("consumption_kbn") == 1 and not cleaned.get("consumption_tax"):
            self.add_error("consumption_tax", "外税の場合は消費税額を入力してください。")
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
        (1, '不使用'),
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

    CONSUMPTION_KBN_CHOICES = [
        ('', '--'),
        (0, '内税'),
        (1, '外税'),
    ]
    # 内税をデフォルト選択
    consumption_kbn = forms.TypedChoiceField(
        label='内外税区分',
        required=False,
        choices=CONSUMPTION_KBN_CHOICES,
        coerce=lambda x: int(x) if x != '' else None,
        empty_value=None,
        initial=0,
        widget=forms.Select(attrs={'class': 'form-select form-select-sm'}),
    )

    class Meta:
        model = T_DocumentContent
        fields = ['date', 'amount', 'shiharaisaki', 'tekikaku_cd', 'corpo_card', 'corpo_card_no', 'consumption_kbn', 'consumption_tax']
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
        self.fields['consumption_tax'] = CommaDecimalField(
            required=False, max_digits=10, decimal_places=2,
            label='消費税額',
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
        self.fields['corpo_card'].choices = _get_item_choices(
            'COC',
            fallback=[('', '選択してください'), ('1', '不使用'), ('2', 'コーポレートカード支払い')],
        )
        self.fields['consumption_kbn'].choices = _get_item_choices(
            'TAX',
            empty_label='--',
            fallback=[('', '--'), ('0', '内税'), ('1', '外税')],
        )
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
        # 外税選択時は消費税額必須（下書き時はスキップ）
        if not self.is_draft and cleaned.get("consumption_kbn") == 1 and not cleaned.get("consumption_tax"):
            self.add_error("consumption_tax", "外税の場合は消費税額を入力してください。")
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
        (1, '不使用'),
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

    CONSUMPTION_KBN_CHOICES = [
        ('', '--'),
        (0, '内税'),
        (1, '外税'),
    ]
    # 内税をデフォルト選択
    consumption_kbn = forms.TypedChoiceField(
        label='内外税区分',
        required=False,
        choices=CONSUMPTION_KBN_CHOICES,
        coerce=lambda x: int(x) if x != '' else None,
        empty_value=None,
        initial=0,
        widget=forms.Select(attrs={'class': 'form-select form-select-sm'}),
    )

    class Meta:
        model = T_DocumentContent
        fields = ['date', 'amount', 'shiharaisaki', 'tekikaku_cd', 'corpo_card', 'corpo_card_no', 'consumption_kbn', 'consumption_tax']
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
        self.fields['consumption_tax'] = CommaDecimalField(
            required=False, max_digits=10, decimal_places=2,
            label='消費税額',
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
        self.fields['corpo_card'].choices = _get_item_choices(
            'COC',
            fallback=[('', '選択してください'), ('1', '不使用'), ('2', 'コーポレートカード支払い')],
        )
        self.fields['consumption_kbn'].choices = _get_item_choices(
            'TAX',
            empty_label='--',
            fallback=[('', '--'), ('0', '内税'), ('1', '外税')],
        )
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
        # 外税選択時は消費税額必須（下書き時はスキップ）
        if not self.is_draft and cleaned.get('consumption_kbn') == 1 and not cleaned.get('consumption_tax'):
            self.add_error('consumption_tax', '外税の場合は消費税額を入力してください。')
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


# ── 固定資産台帳 編集・新規登録フォーム ─────────────────────────────────────
# v_assets の68列（import_assets.py の ACCESS_COLUMNS と同一の並び）を
# 「基本情報 / 取得・償却 / 設置場所 / 除却 / 管理情報」の5セクションに分類する。

ASSET_READONLY_FIELDS = [
    'account_name', 'bumon_name', 'accounting_bumon_cd', 'structure_name',
    'detail_name', 'location_name', 'city_cd', 'city_name',
]

ASSET_MONEY_FIELDS = [
    'acquisition_amount', 'beginning_amount', 'beginning_depreciation_diff', 'residual_amount',
    'current_optional_depreciation', 'compression_reserve', 'beginning_adjustment', 'depreciation_limit',
    'disposal_amount', 'special_depreciation_amount', 'extra_depreciation_amount',
    'prev_year_book_amount', 'prev_year_assessed_amount', 'switch_book_amount', 'post_switch_annual_depreciation',
]

ASSET_DATE_FIELDS = [
    'depreciation_start_date', 'acquisition_date', 'transfer_date', 'installation_date',
    'disposal_date', 'registration_date', 'disposal_registration_date', 'transfer_registration_date',
    'special_registration_date', 'depreciation_stop_start_date', 'depreciation_stop_end_date',
    'straight_line_switch_date',
]

ASSET_SECTIONS = [
    ('基本情報', [
        'asset_no', 'account_cd', 'account_name', 'bumon_cd', 'bumon_name',
        'accounting_bumon_cd', 'asset_name1', 'asset_name2', 'structure_cd',
        'structure_name', 'detail_name', 'alloc_kbn', 'alloc_rate_cd', 'quantity', 'unit',
    ]),
    ('取得・償却', [
        'useful_life', 'depreciation_start_date', 'acquisition_date', 'transfer_date',
        'acquisition_amount', 'beginning_amount', 'beginning_depreciation_diff', 'residual_amount',
        'current_optional_depreciation', 'current_optional_kbn', 'compression_reserve',
        'beginning_adjustment', 'depreciation_limit', 'collateral_kbn', 'special_depreciation_kbn',
        'extra_depreciation_kbn', 'special_depreciation_amount', 'extra_depreciation_amount',
        'special_rate_input_kbn', 'special_rate_numerator', 'special_rate_denominator',
        'straight_line_switch_date', 'switch_book_amount', 'post_switch_annual_depreciation',
        'prev_year_book_amount', 'prev_year_assessed_amount', 'depreciation_stop_start_date',
        'depreciation_stop_end_date',
    ]),
    ('設置場所', [
        'location_cd', 'location_name', 'city_cd', 'city_name', 'tax_target_kbn', 'installation_date',
    ]),
    ('除却', [
        'disposal_kbn', 'disposal_date', 'disposal_amount', 'disposal_registration_date',
        'increase_reason', 'decrease_kbn', 'transfer_registration_date', 'special_registration_date',
        'registration_date', 'source_asset_no', 'partial_expansion_asset_cd', 'supplier_cd',
    ]),
    ('管理情報', [
        'ringi_no', 'manager', 'memo1', 'memo2', 'model_name', 'serial_no', 'physical_inventory_result',
    ]),
]

ASSET_ALL_FIELDS = [name for _, names in ASSET_SECTIONS for name in names]

# 同期キューへの差分payload対象（PKと読み取り専用8項目を除く59項目）
ASSET_EDITABLE_FIELDS = [
    name for name in ASSET_ALL_FIELDS
    if name != 'asset_no' and name not in ASSET_READONLY_FIELDS
]


def get_asset_register_form(data=None, instance=None, is_edit=False):
    """固定資産台帳の編集・新規登録フォームを生成する。
    is_edit=True の場合は asset_no も disabled にする（PK変更不可）。"""
    from django.forms import modelform_factory
    FormClass = modelform_factory(T_Assets, fields=ASSET_ALL_FIELDS)
    form = FormClass(data=data, instance=instance)

    for name in ASSET_MONEY_FIELDS:
        form.fields[name] = CommaDecimalField(
            required=False, max_digits=18, decimal_places=4,
            label=form.fields[name].label,
            widget=forms.TextInput(attrs={
                'class': 'form-control', 'inputmode': 'numeric',
                'data-amount-input': '', 'autocomplete': 'off',
            }),
        )

    for name in ASSET_DATE_FIELDS:
        form.fields[name].widget = forms.DateInput(
            attrs={'type': 'date', 'class': 'form-control'}, format='%Y-%m-%d',
        )
        form.fields[name].input_formats = ['%Y-%m-%d']

    for name in ASSET_READONLY_FIELDS:
        form.fields[name].disabled = True
        form.fields[name].required = False

    if is_edit:
        form.fields['asset_no'].disabled = True

    for name, field in form.fields.items():
        if name in ASSET_MONEY_FIELDS or name in ASSET_DATE_FIELDS:
            continue
        w = field.widget
        if isinstance(w, forms.Select):
            w.attrs['class'] = (w.attrs.get('class', '') + ' form-select').strip()
        elif not isinstance(w, forms.CheckboxInput):
            w.attrs['class'] = (w.attrs.get('class', '') + ' form-control').strip()

    return form

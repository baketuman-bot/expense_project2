from django import template
from django.template.defaultfilters import stringfilter

register = template.Library()

@register.filter
def get_item(dictionary, key):
    """辞書のキー参照フィルター: {{ my_dict|get_item:variable_key }}"""
    if dictionary is None:
        return None
    return dictionary.get(key)

@register.filter
@stringfilter
def is_image(filename):
    """
    ファイル名から画像ファイルかどうかを判定するフィルター
    """
    ext = filename.lower()
    return ext.endswith(('.jpg', '.jpeg', '.png', '.gif'))

@register.filter
@stringfilter
def is_pdf(filename):
    """
    ファイル名からPDFファイルかどうかを判定するフィルター
    """
    return filename.lower().endswith('.pdf')

@register.filter
def currency_display(tsuka_cd):
    """通貨コード(tsuka_cd)をm_item.contentの通貨名に変換する。JPYは¥、未設定時は¥を返す。"""
    if not tsuka_cd:
        return '¥'
    try:
        from expenses.models import M_Item
        item = M_Item.objects.filter(data_kbn='CUR', key=tsuka_cd).first()
        if item:
            if item.content == 'JPY':
                return '¥'
            return item.content
    except Exception:
        pass
    return tsuka_cd

@register.filter
def status_badge_class(status_cd):
    """ステータスコードからステータスピルクラスを返す。"""
    mapping = {
        'INPRO':    'status-pill status-pill-pending',
        'APPROVED': 'status-pill status-pill-mid-approved',
        'REJECTED': 'status-pill status-pill-rejected',
        'RETURNED': 'status-pill status-pill-review',
        'CANCEL':   'status-pill status-pill-cancelled',
        'FNS':      'status-pill status-pill-approved',
        'DRAFT':    'status-pill status-pill-draft',
    }
    return mapping.get(status_cd or '', 'status-pill status-pill-draft')

@register.filter
def status_dot_class(status_cd):
    """タイムラインドット用: ステータスコードからBootstrap bg-*クラスを返す。"""
    mapping = {
        'INPRO': 'bg-primary',
        'APPROVED': 'bg-success',
        'REJECTED': 'bg-danger',
        'RETURNED': 'bg-warning',
        'CANCEL': 'bg-secondary',
        'FNS': 'bg-success',
        'DRAFT': 'bg-secondary',
    }
    return mapping.get(status_cd or '', 'bg-secondary')


@register.filter
def amount_format(amount, tsuka_cd):
    """
    通貨コードに応じて金額をフォーマットする。
    JPY（key='00'またはcontent='JPY'）は小数点なし、それ以外は小数第2位まで表示。
    """
    if amount is None:
        return ''
    try:
        from expenses.models import M_Item
        item = M_Item.objects.filter(data_kbn='CUR', key=tsuka_cd).first()
        is_jpy = (not item) or (item.content == 'JPY')
    except Exception:
        is_jpy = True
    if is_jpy:
        return '{:,.0f}'.format(amount)
    else:
        return '{:,.2f}'.format(amount)
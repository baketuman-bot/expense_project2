# views_assets_low_value.py
# 少額資産台帳（T_AssetsLowValue）ビュー群 — views.py から import して使用
import csv as csv_module

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import StreamingHttpResponse
from django.shortcuts import render

from .models import T_AssetsLowValue


# ── 検索ヘルパー ─────────────────────────────────────────────────────────────

def _filter_low_value_assets(get_params):
    """GET パラメータを受け取り、フィルタ済み T_AssetsLowValue QuerySet を返す"""
    qs = T_AssetsLowValue.objects.all().order_by('low_value_asset_no')

    keyword   = get_params.get('keyword', '').strip()
    bumon_cd  = get_params.get('bumon_cd', '').strip()
    date_from = get_params.get('date_from', '').strip()
    date_to   = get_params.get('date_to', '').strip()

    if keyword:
        qs = qs.filter(
            Q(low_value_asset_no__icontains=keyword) |
            Q(item_name__icontains=keyword)           |
            Q(maker_name__icontains=keyword)           |
            Q(model_no__icontains=keyword)             |
            Q(serial_no__icontains=keyword)
        )
    if bumon_cd:
        qs = qs.filter(bumon_cd=bumon_cd)
    if date_from:
        qs = qs.filter(acquisition_date__date__gte=date_from)
    if date_to:
        qs = qs.filter(acquisition_date__date__lte=date_to)

    return qs


# ── 一覧・検索 ───────────────────────────────────────────────────────────────

@login_required
def assets_low_value_list(request):
    """少額資産台帳 一覧・検索"""
    qs = _filter_low_value_assets(request.GET)

    bumon_choices = (
        T_AssetsLowValue.objects
        .exclude(bumon_cd='').exclude(bumon_cd__isnull=True)
        .values_list('bumon_cd', 'bumon_name')
        .order_by('bumon_cd').distinct()
    )

    paginator = Paginator(qs, 50)
    page_obj  = paginator.get_page(request.GET.get('page'))

    return render(request, 'expenses/assets_low_value_list.html', {
        'current':         'assets_low_value_list',
        'page_obj':        page_obj,
        'total_count':     paginator.count,
        'keyword':         request.GET.get('keyword', ''),
        'bumon_cd':        request.GET.get('bumon_cd', ''),
        'date_from':       request.GET.get('date_from', ''),
        'date_to':         request.GET.get('date_to', ''),
        'bumon_choices':   list(bumon_choices),
    })


# ── CSV 出力 ─────────────────────────────────────────────────────────────────

_CSV_HEADERS = [
    '小額資産番号', 'メーカー名', '品名', '品番', '製造番号', '用途',
    '取得価格', '年月日', '部門コード', '部門名', '設置場所コード', '設置場所名',
    '作成日', '更新日',
]


def _low_value_asset_to_row(a):
    def d(v):
        return v.strftime('%Y/%m/%d') if v else ''

    def n(v):
        return str(v) if v is not None else ''

    return [
        a.low_value_asset_no or '',
        a.maker_name or '',
        a.item_name or '',
        a.model_no or '',
        a.serial_no or '',
        a.purpose or '',
        n(a.acquisition_price),
        d(a.acquisition_date),
        a.bumon_cd or '',
        a.bumon_name or '',
        a.location_cd or '',
        a.location_name or '',
        d(a.cre_date),
        d(a.up_date),
    ]


@login_required
def assets_low_value_csv(request):
    """少額資産台帳 CSV ダウンロード（検索条件を引き継ぐ）"""
    qs = _filter_low_value_assets(request.GET)

    class EchoBuffer:
        def write(self, value):
            return value

    writer = csv_module.writer(EchoBuffer())

    def rows():
        yield writer.writerow(_CSV_HEADERS)
        for a in qs.iterator():
            yield writer.writerow(_low_value_asset_to_row(a))

    response = StreamingHttpResponse(rows(), content_type='text/csv; charset=utf-8-sig')
    response['Content-Disposition'] = 'attachment; filename="assets_low_value_register.csv"'
    return response

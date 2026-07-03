# views_assets_register.py
# 固定資産台帳（T_ASSETS）ビュー群 — views.py から import して使用
import csv as csv_module
from datetime import datetime
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import StreamingHttpResponse
from django.shortcuts import render, redirect, get_object_or_404

from .models import T_Assets, T_AssetsSyncQueue
from .forms import get_asset_register_form, ASSET_SECTIONS, ASSET_EDITABLE_FIELDS


# ── 検索ヘルパー ─────────────────────────────────────────────────────────────

def _filter_assets(get_params):
    """GET パラメータを受け取り、フィルタ済み T_Assets QuerySet を返す"""
    qs = T_Assets.objects.all().order_by('asset_no')

    keyword    = get_params.get('keyword', '').strip()
    bumon_cd   = get_params.get('bumon_cd', '').strip()
    account_cd = get_params.get('account_cd', '').strip()
    disposal   = get_params.get('disposal', '').strip()   # '0'=在籍, '1'=除却済
    date_from  = get_params.get('date_from', '').strip()
    date_to    = get_params.get('date_to', '').strip()

    if keyword:
        qs = qs.filter(
            Q(asset_no__icontains=keyword)    |
            Q(asset_name1__icontains=keyword) |
            Q(asset_name2__icontains=keyword) |
            Q(ringi_no__icontains=keyword)    |
            Q(manager__icontains=keyword)     |
            Q(serial_no__icontains=keyword)
        )
    if bumon_cd:
        qs = qs.filter(bumon_cd=bumon_cd)
    if account_cd:
        qs = qs.filter(account_cd=account_cd)
    if disposal == '0':
        qs = qs.filter(Q(disposal_kbn='') | Q(disposal_kbn__isnull=True))
    elif disposal == '1':
        qs = qs.exclude(Q(disposal_kbn='') | Q(disposal_kbn__isnull=True))
    if date_from:
        qs = qs.filter(acquisition_date__date__gte=date_from)
    if date_to:
        qs = qs.filter(acquisition_date__date__lte=date_to)

    return qs


# ── 一覧・検索 ───────────────────────────────────────────────────────────────

@login_required
def assets_register_list(request):
    """固定資産台帳 一覧・検索"""
    qs = _filter_assets(request.GET)

    bumon_choices = (
        T_Assets.objects
        .exclude(bumon_cd='').exclude(bumon_cd__isnull=True)
        .values_list('bumon_cd', 'bumon_name')
        .order_by('bumon_cd').distinct()
    )
    account_choices = (
        T_Assets.objects
        .exclude(account_cd='').exclude(account_cd__isnull=True)
        .values_list('account_cd', 'account_name')
        .order_by('account_cd').distinct()
    )

    paginator = Paginator(qs, 50)
    page_obj  = paginator.get_page(request.GET.get('page'))

    can_manage_assets = _can_manage_assets(request.user)
    pending_sync_count = (
        T_AssetsSyncQueue.objects.filter(status='pending').count()
        if can_manage_assets else 0
    )

    return render(request, 'expenses/assets_register_list.html', {
        'current':         'assets_register_list',
        'page_obj':        page_obj,
        'total_count':     paginator.count,
        'keyword':         request.GET.get('keyword', ''),
        'bumon_cd':        request.GET.get('bumon_cd', ''),
        'account_cd':      request.GET.get('account_cd', ''),
        'disposal':        request.GET.get('disposal', ''),
        'date_from':       request.GET.get('date_from', ''),
        'date_to':         request.GET.get('date_to', ''),
        'bumon_choices':   list(bumon_choices),
        'account_choices': list(account_choices),
        'can_manage_assets': can_manage_assets,
        'pending_sync_count':  pending_sync_count,
    })


# ── CSV 出力 ─────────────────────────────────────────────────────────────────

_CSV_HEADERS = [
    '資産NO', '科目コード', '科目名', '部門コード', '部門名', '会計用部門コード',
    '資産名１', '資産名２', '構造細目コード', '構造名', '細目名',
    '部門配賦区分', '配賦率コード', '個数', '単位', '耐用年数',
    '償却開始日', '取得日', '異動増日付', '設置日', '除却日',
    '固定登録日', '除却登録日', '異動登録日', '特割登録日',
    '償却停止開始日', '償却停止終了日', '定額切換日',
    '取得価額', '期首価額', '期首償却過不足額', '残存価額',
    '当期任意償却額', '圧縮引当金', '期首価額調整額', '償却可能限度額',
    '処分価額', '特別償却額', '割増償却額',
    '前年申告帳簿価額', '前年申告評価額', '切換時帳簿価額', '切換後年償却額',
    '当期任意償却区分', '特例率入力区分',
    '担保資産区分', '特別償却計算区分', '割増償却計算区分',
    '納税対象区分', '増加事由', '除却区分', '減少区分',
    '設置場所コード', '設置場所名', '市区町村コード', '市区町村名',
    '特例率分子', '特例率分母',
    '異動元資産NO', '購入先コード', '一部増設元資産コード',
    '稟議NO', '管理者', 'メモ欄', 'メモ欄２', 'モデル', 'シリアルNO', '実地調査結果',
]


def _asset_to_row(a):
    def d(v):
        return v.strftime('%Y/%m/%d') if v else ''

    def n(v):
        return str(v) if v is not None else ''

    return [
        a.asset_no or '',
        a.account_cd or '',
        a.account_name or '',
        a.bumon_cd or '',
        a.bumon_name or '',
        a.accounting_bumon_cd or '',
        a.asset_name1 or '',
        a.asset_name2 or '',
        a.structure_cd or '',
        a.structure_name or '',
        a.detail_name or '',
        a.alloc_kbn or '',
        a.alloc_rate_cd or '',
        n(a.quantity),
        a.unit or '',
        n(a.useful_life),
        d(a.depreciation_start_date),
        d(a.acquisition_date),
        d(a.transfer_date),
        d(a.installation_date),
        d(a.disposal_date),
        d(a.registration_date),
        d(a.disposal_registration_date),
        d(a.transfer_registration_date),
        d(a.special_registration_date),
        d(a.depreciation_stop_start_date),
        d(a.depreciation_stop_end_date),
        d(a.straight_line_switch_date),
        n(a.acquisition_amount),
        n(a.beginning_amount),
        n(a.beginning_depreciation_diff),
        n(a.residual_amount),
        n(a.current_optional_depreciation),
        n(a.compression_reserve),
        n(a.beginning_adjustment),
        n(a.depreciation_limit),
        n(a.disposal_amount),
        n(a.special_depreciation_amount),
        n(a.extra_depreciation_amount),
        n(a.prev_year_book_amount),
        n(a.prev_year_assessed_amount),
        n(a.switch_book_amount),
        n(a.post_switch_annual_depreciation),
        n(a.current_optional_kbn),
        n(a.special_rate_input_kbn),
        a.collateral_kbn or '',
        a.special_depreciation_kbn or '',
        a.extra_depreciation_kbn or '',
        a.tax_target_kbn or '',
        a.increase_reason or '',
        a.disposal_kbn or '',
        a.decrease_kbn or '',
        a.location_cd or '',
        a.location_name or '',
        a.city_cd or '',
        a.city_name or '',
        n(a.special_rate_numerator),
        n(a.special_rate_denominator),
        a.source_asset_no or '',
        a.supplier_cd or '',
        a.partial_expansion_asset_cd or '',
        a.ringi_no or '',
        a.manager or '',
        a.memo1 or '',
        a.memo2 or '',
        a.model_name or '',
        a.serial_no or '',
        a.physical_inventory_result or '',
    ]


@login_required
def assets_register_csv(request):
    """固定資産台帳 CSV ダウンロード（検索条件を引き継ぐ）"""
    qs = _filter_assets(request.GET)

    class EchoBuffer:
        def write(self, value):
            return value

    writer = csv_module.writer(EchoBuffer())

    def rows():
        yield writer.writerow(_CSV_HEADERS)
        for a in qs.iterator():
            yield writer.writerow(_asset_to_row(a))

    response = StreamingHttpResponse(rows(), content_type='text/csv; charset=utf-8-sig')
    response['Content-Disposition'] = 'attachment; filename="assets_register.csv"'
    return response


# ── 権限・共通ヘルパー ────────────────────────────────────────────────────────

def _can_manage_assets(user):
    """固定資産台帳の編集・新規登録・同期キュー閲覧が許可されているか判定する。"""
    return user.has_role('accountant') or user.has_role('admin')


def _serialize_payload_value(value):
    """T_AssetsSyncQueue.payload に格納するためJSON化可能な値へ変換する。"""
    if isinstance(value, datetime):
        return value.strftime('%Y-%m-%d %H:%M:%S')
    if isinstance(value, Decimal):
        return str(value)
    return value


def _build_asset_form_sections(form):
    """フォームをセクション単位の BoundField リストへ組み替える（テンプレート用）"""
    return [(title, [form[name] for name in names]) for title, names in ASSET_SECTIONS]


# ── 編集・新規登録 ────────────────────────────────────────────────────────────

@login_required
def assets_register_edit(request, asset_no):
    """固定資産台帳 編集（accountant/admin ロール限定）"""
    if not _can_manage_assets(request.user):
        raise PermissionDenied()

    obj = get_object_or_404(T_Assets, pk=asset_no)
    original_values = {name: getattr(obj, name) for name in ASSET_EDITABLE_FIELDS}

    if request.method == 'POST':
        form = get_asset_register_form(data=request.POST, instance=obj, is_edit=True)
        if form.is_valid():
            diff = {}
            for name in ASSET_EDITABLE_FIELDS:
                new_val = form.cleaned_data.get(name)
                if original_values[name] != new_val:
                    diff[name] = _serialize_payload_value(new_val)
                    setattr(obj, name, new_val)
            if diff:
                with transaction.atomic():
                    obj.save(update_fields=list(diff.keys()))
                    T_AssetsSyncQueue.objects.create(
                        asset_no=obj.asset_no,
                        operation='update',
                        payload=diff,
                        created_by=request.user,
                    )
            return redirect('expenses:assets_register_list')
    else:
        form = get_asset_register_form(instance=obj, is_edit=True)

    return render(request, 'expenses/assets_register_form.html', {
        'form': form,
        'form_sections': _build_asset_form_sections(form),
        'is_create': False,
        'asset_no': asset_no,
    })


# ── Task 4・5 で正式実装に置き換えるまでの一時スタブ（circular importを避けるため） ──

@login_required
def assets_register_create(request):
    """固定資産台帳 新規登録（accountant/admin ロール限定）"""
    if not _can_manage_assets(request.user):
        raise PermissionDenied()

    if request.method == 'POST':
        form = get_asset_register_form(data=request.POST, is_edit=False)
        form.validate_unique = lambda: None  # 独自の重複チェック（T_Assets + 未送信キュー）で判定するため、標準のPK一意性検証は無効化
        if form.is_valid():
            asset_no = form.cleaned_data['asset_no']
            duplicate = (
                T_Assets.objects.filter(pk=asset_no).exists()
                or T_AssetsSyncQueue.objects.filter(
                    asset_no=asset_no, operation='insert', status='pending',
                ).exists()
            )
            if duplicate:
                form.add_error('asset_no', 'この資産NOは既に登録されています。')
            else:
                with transaction.atomic():
                    obj = form.save()
                    payload = {
                        name: _serialize_payload_value(form.cleaned_data.get(name))
                        for name in ASSET_EDITABLE_FIELDS
                        if form.cleaned_data.get(name) not in (None, '')
                    }
                    T_AssetsSyncQueue.objects.create(
                        asset_no=obj.asset_no,
                        operation='insert',
                        payload=payload,
                        created_by=request.user,
                    )
                return redirect('expenses:assets_register_list')
    else:
        form = get_asset_register_form(is_edit=False)

    return render(request, 'expenses/assets_register_form.html', {
        'form': form,
        'form_sections': _build_asset_form_sections(form),
        'is_create': True,
    })


@login_required
def assets_sync_queue_list(request):
    """固定資産台帳 同期キュー一覧（accountant/admin ロール限定）"""
    if not _can_manage_assets(request.user):
        raise PermissionDenied()

    status_filter = request.GET.get('status', '').strip()
    qs = T_AssetsSyncQueue.objects.select_related('created_by').order_by('-created_at')
    if status_filter in dict(T_AssetsSyncQueue.STATUS_CHOICES):
        qs = qs.filter(status=status_filter)

    paginator = Paginator(qs, 50)
    page_obj = paginator.get_page(request.GET.get('page'))

    return render(request, 'expenses/assets_sync_queue_list.html', {
        'page_obj': page_obj,
        'total_count': paginator.count,
        'status_filter': status_filter,
        'status_choices': T_AssetsSyncQueue.STATUS_CHOICES,
        'pending_count': T_AssetsSyncQueue.objects.filter(status='pending').count(),
        'error_count': T_AssetsSyncQueue.objects.filter(status='error').count(),
    })


@login_required
def assets_sync_info(request):
    """固定資産台帳 MDB同期の案内（仕組み・注意事項）。accountant/admin ロール限定。

    sync_assets.bat は fpack が稼働する Windows 機のデスクトップから手動実行する
    スタンドアロンスクリプトであり、Web（Django）からは起動できない。このページは
    その手順・仕組み・注意事項を案内するのみで、実行のトリガーは持たない。
    """
    if not _can_manage_assets(request.user):
        raise PermissionDenied()

    return render(request, 'expenses/assets_sync_info.html', {
        'pending_count': T_AssetsSyncQueue.objects.filter(status='pending').count(),
        'error_count': T_AssetsSyncQueue.objects.filter(status='error').count(),
    })

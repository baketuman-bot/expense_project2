from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.conf import settings
from .models import (
    M_User, M_Status, M_Account, T_Document, T_DocumentContent,
    M_Group, M_Bumon, M_Post, M_Item, M_DocumentType, M_DocumentField, M_AccountDocument,
    V_Group, M_BelongTo, T_WorkflowInstance, T_WorkflowAction, T_DocumentApprover,
    T_DocumentAttachment, M_WorkflowTemplate, M_WorkflowStep, M_DocumentGroup,
)
from .forms import (
    ExpenseDetailFormSet, ExpenseDetailEditFormSet, ApprovalForm,
    TravelDetailFormSet, TravelDetailEditFormSet,
    AccommodationFormSet, AccommodationEditFormSet,
    AllowanceFormSet, AllowanceEditFormSet,
)
from .utils import send_notification, steps_with_candidates, get_pending_approvers, candidates_for_step
from django.utils import timezone
import uuid
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse, HttpResponseBadRequest, HttpResponse, Http404
from django.core.paginator import Paginator
from django.forms import modelform_factory
import csv

from django.core.files.base import ContentFile
import io


def _is_travel_doc_type(doc_type):
    """出張旅費精算（menu_group='TRV'）か判定する。"""
    mg = getattr(doc_type, 'menu_group', None)
    return bool(mg and getattr(mg, 'menu_group', None) == 'TRV')


def _is_lon_doc_type(doc_type):
    """前借証 (LON グループ) かどうか判定する。"""
    mg = getattr(doc_type, 'menu_group', None)
    return bool(mg and getattr(mg, 'menu_group', None) == 'LON')


def _resolve_dynamic_fields_doc_type(doc_type):
    """同グループ内で M_DocumentField が定義されている代表 DocType を返す。
    doc_type 自身に定義があればそれを、なければ同 menu_group の他 DocType を探す。
    """
    if not doc_type:
        return None
    if M_DocumentField.objects.filter(document_type=doc_type).exists():
        return doc_type
    mg = getattr(doc_type, 'menu_group', None)
    if not mg:
        return None
    rep_id = (M_DocumentField.objects
              .filter(document_type__menu_group=mg)
              .values_list('document_type_id', flat=True)
              .first())
    if rep_id is None:
        return None
    return M_DocumentType.objects.filter(document_type_id=rep_id).first()


def _has_dynamic_fields(doc_type):
    """M_DocumentField でフィールド定義されている DocType か（同グループ含む）判定する。"""
    return _resolve_dynamic_fields_doc_type(doc_type) is not None


def _asset_form_context(doc_type):
    """カテゴリが 'assets' の DocType に適用するフォーム表示制御コンテキストを返す。"""
    mg = getattr(doc_type, 'menu_group', None)
    mg_code = getattr(mg, 'menu_group', None)
    if doc_type and mg and getattr(mg, 'category', None) == 'assets':
        return {
            'hide_currency': True,
            'hide_pay_kbn': True,
            'purpose_label': '固定資産名',
            'receipt_label': '資産画像',
            'detail_section_title': '固定資産明細',
            'hide_detail_fields': True,
            'reorder_sections': True,
            'info_first': False,
            'hide_receipt_fields': False,
        }
    return {
        'hide_currency': False,
        'hide_pay_kbn': False,
        'purpose_label': None,
        'receipt_label': None,
        'detail_section_title': None,
        'hide_detail_fields': False,
        'reorder_sections': False,
        'info_first': True,
        'hide_receipt_fields': mg_code == 'LON',
    }


def _apply_created_at_date_range(qs, date_from, date_to):
    """created_at に対する日付範囲フィルタを、MySQL の timezone テーブル有無に依存しない形で適用する。

    Django の __date ルックアップは CONVERT_TZ() を使うため、mysql.time_zone_name が未ロードだと
    常に NULL を返し 0 件となる。ここでは datetime 範囲に変換して比較する。
    """
    from datetime import datetime, time, timedelta
    if date_from:
        try:
            d = datetime.strptime(date_from, "%Y-%m-%d").date()
            start_dt = timezone.make_aware(datetime.combine(d, time.min))
            qs = qs.filter(created_at__gte=start_dt)
        except (ValueError, TypeError):
            pass
    if date_to:
        try:
            d = datetime.strptime(date_to, "%Y-%m-%d").date()
            end_dt = timezone.make_aware(datetime.combine(d + timedelta(days=1), time.min))
            qs = qs.filter(created_at__lt=end_dt)
        except (ValueError, TypeError):
            pass
    return qs


def _build_dynamic_fields_display(expense):
    """T_Document の動的フィールドを表示用リストで返す。
    戻り値: [{'label', 'value', 'col_width', 'row_break', 'is_label', 'calc_formula'}, ...] または []
    """
    result = []
    try:
        doc_type = getattr(expense, 'document_type', None)
        field_doc_type = _resolve_dynamic_fields_doc_type(doc_type)
        if not field_doc_type:
            return []
        first_detail = expense.contents.order_by('document_detail_id').first()
        stored = first_detail.content if (first_detail and isinstance(first_detail.content, dict)) else {}
        defs = M_DocumentField.objects.filter(document_type=field_doc_type).order_by('field_order', 'field_name')
        for d in defs:
            raw_type = (d.field_type or '').strip().lower()
            label = d.field_name_view or d.field_name
            is_label = (raw_type == 'label')
            if is_label:
                # label型は保存値なし。計算式を持つ場合は calc_formula を渡す
                result.append({
                    'label':        label,
                    'value':        '',
                    'col_width':    d.col_width or 4,
                    'row_break':    d.row_break,
                    'is_label':     True,
                    'calc_formula': d.calc_formula or '',
                    'field_help_text': d.field_help_text or '',
                    'name':         d.field_name,
                })
                continue
            raw_val = stored.get(d.field_name, '')
            # select 型は key → content に変換
            if raw_type.startswith('select') and raw_val:
                parts = raw_type.split(':', 1)
                if len(parts) == 2:
                    item = M_Item.objects.filter(data_kbn__iexact=parts[1].strip(), key=raw_val).first()
                    display_val = item.content if item else raw_val
                else:
                    display_val = raw_val
            else:
                display_val = raw_val
            result.append({
                'label':        label,
                'value':        display_val or '-',
                'col_width':    d.col_width or 4,
                'row_break':    d.row_break,
                'is_label':     False,
                'calc_formula': '',
                'field_help_text': d.field_help_text or '',
                'name':         d.field_name,
            })
    except Exception:
        result = []
    return result


def _build_approval_request_mail(expense, prefix=""):
    """承認依頼メールの件名・本文を生成する共通ヘルパー。
    prefix: 本文冒頭に付ける文字列（例: '【再申請】'）
    """
    try:
        applicant = getattr(expense.man_number, 'user_name', '') or ''
    except Exception:
        applicant = ''
    doc_id = expense.document_id
    subject = f"[経費精算] 承認依頼: ID {doc_id} {applicant}"

    try:
        updated_at_val = expense.updated_at
        if updated_at_val:
            local_dt = timezone.localtime(updated_at_val)
            updated_at_str = local_dt.strftime("%Y年%m月%d日 %H:%M")
        else:
            updated_at_str = ''
    except Exception:
        updated_at_str = ''

    try:
        doc_type_name = expense.document_type.document_type_name or ''
    except Exception:
        doc_type_name = ''

    try:
        tsuka_cd_val = expense.tsuka_cd or ''
        tsuka_disp = (
            M_Item.objects.filter(data_kbn='CUR', key=tsuka_cd_val)
            .values_list('content', flat=True)
            .first()
        ) or tsuka_cd_val
    except Exception:
        tsuka_disp = ''

    amount = expense.total_amount or 0
    prefix_line = f"{prefix}" if prefix else ""

    body = (
        f"{prefix_line}承認申請が提出されました。\n"
        f"申請者: {applicant}\n"
        f"日付：{updated_at_str}\n"
        f"申請：{doc_type_name}\n"
        f"タイトル: {expense.title or ''}\n"
        f"合計金額: {tsuka_disp} {amount}\n"
        f"\n"
        f"費用処理アプリ\n"
        f"{settings.SITE_URL}/\n"
    )
    return subject, body


def _get_bumons_for_user(user, doc_type=None):
    """doc_type.bumon_scope に従って負担部門リストを返す。
    bumon_scope=1 (全部門) → M_Bumon 全件
    bumon_scope=0 (自グループ絞り込み・デフォルト) → 申請者グループ起点でフィルタ

    SQL ロジック (scope=0):
        SELECT g.group_cd FROM v_group g
        WHERE g.relation_group_cd IN (
            SELECT bb.group_cd_id FROM m_belong_to bb WHERE bb.man_number_id = <user>
        )
    得られた group_cd に所属するユーザーの bumon_cd を収集し M_Bumon を絞り込む。
    フィルタ失敗・所属なし時は全件を返す。
    """
    # bumon_scope=1 なら全件返す
    scope = getattr(doc_type, 'bumon_scope', 0) if doc_type else 0
    if scope == 1:
        return M_Bumon.objects.all().order_by('bumon_cd')

    try:
        # 1. 申請者の所属グループコード
        applicant_group_cds = list(
            M_BelongTo.objects.filter(man_number=user)
            .values_list('group_cd_id', flat=True)
        )
        if not applicant_group_cds:
            return M_Bumon.objects.all().order_by('bumon_cd')

        # 2. v_group: relation_group_cd が申請者グループに含まれる group_cd を取得
        filtered_group_cds = list(
            V_Group.objects
            .filter(relation_group_cd__in=applicant_group_cds)
            .values_list('group_cd', flat=True)
            .distinct()
        )
        if not filtered_group_cds:
            return M_Bumon.objects.all().order_by('bumon_cd')

        # 3. 対象グループに所属するユーザーの bumon_cd を収集
        bumon_cds = list(
            M_BelongTo.objects
            .filter(group_cd_id__in=filtered_group_cds)
            .values_list('man_number__bumon_cd', flat=True)
            .distinct()
        )
        bumon_cds = [b for b in bumon_cds if b]
        if not bumon_cds:
            return M_Bumon.objects.all().order_by('bumon_cd')

        return M_Bumon.objects.filter(bumon_cd__in=bumon_cds).order_by('bumon_cd')
    except Exception:
        return M_Bumon.objects.all().order_by('bumon_cd')


def _get_account_queryset(doc_type):
    """doc_type に紐づく M_AccountDocument が存在すればその勘定科目のみ、なければ全件を返す。"""
    if doc_type is None:
        return M_Account.objects.all().order_by('account_cd')
    linked = M_AccountDocument.objects.filter(document_type=doc_type).values_list('account_cd_id', flat=True)
    if linked.exists():
        return M_Account.objects.filter(account_cd__in=linked).order_by('account_cd')
    return M_Account.objects.all().order_by('account_cd')
import base64
import qrcode

from .cloud_receipts import (
    CloudReceiptFetchError,
    fetch_receipt_by_seq,
    fetch_receipts_by_upload_id,
    normalize_seq,
    parse_cloud_receipt_tokens,
)

@login_required
def home(request):
    from .models import T_DocumentApprover

    # 承認待ち（自分が承認者に登録されていて、ステータスがSUBの申請）上位5件
    approver_doc_ids = T_DocumentApprover.objects.filter(
        man_number=request.user
    ).values_list('document_id', flat=True)
    pending_approvals = T_Document.objects.filter(
        document_id__in=approver_doc_ids,
        status_cd__status_cd='INPRO',
    ).order_by('created_at')[:5]

    # 申請中一覧（自分の費用精算カテゴリ申請で承認完了・下書き・取消以外）
    in_progress_expenses = T_Document.objects.filter(
        man_number=request.user,
        document_type__menu_group__category='expense',
    ).exclude(
        status_cd__status_cd__in=['DRAFT', 'CANCEL', 'FNS', 'REJECTED']
    ).order_by('-created_at')[:5]

    # 下書き一覧（自分の費用精算カテゴリ下書き）
    draft_expenses = T_Document.objects.filter(
        man_number=request.user,
        document_type__menu_group__category='expense',
        status_cd__status_cd='DRAFT',
    ).order_by('-created_at')[:5]

    # 承認進行マップ（pending_approvals + in_progress_expenses 両方）
    home_doc_ids = (
        [d.document_id for d in pending_approvals] +
        [d.document_id for d in in_progress_expenses]
    )
    progress_by_doc = _get_step_progress_map(home_doc_ids)

    context = {
        'user': request.user,
        'pending_approvals': pending_approvals,
        'in_progress_expenses': in_progress_expenses,
        'draft_expenses': draft_expenses,
        'progress_by_doc': progress_by_doc,
    }
    return render(request, "expenses/home.html", context)

@login_required
def expense_list(request):
    qs = T_Document.objects.filter(
        man_number=request.user,
        document_type__menu_group__category='expense',
    ).select_related(
        'status_cd', 'document_type', 'bumon_cd'
    ).prefetch_related('contents').order_by("-created_at")

    # フィルター
    status_filter = request.GET.get('status', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    keyword = request.GET.get('keyword', '')

    if status_filter:
        # ドロップダウンの選択値は status_name。同名の複数ステータス(例: 精算完了)をまとめて絞り込む
        qs = qs.filter(status_cd__status_name=status_filter)
    qs = _apply_created_at_date_range(qs, date_from, date_to)
    if keyword:
        qs = qs.filter(
            Q(title__icontains=keyword) |
            Q(contents__purpose__icontains=keyword) |
            Q(contents__shiharaisaki__icontains=keyword) |
            Q(memo__icontains=keyword)
        ).distinct()

    # ページネーション
    paginator = Paginator(qs, 20)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    # status_name 単位で重複除去し、order_by 昇順で並べる
    from django.db.models import Min
    statuses = (
        M_Status.objects
        .values('status_name')
        .annotate(min_order=Min('order_by'))
        .order_by('min_order', 'status_name')
    )

    # 承認進行マップ（ステータスバッジに current/total を表示するため）
    progress_by_doc = _get_step_progress_map([d.document_id for d in page_obj])

    return render(request, "expenses/expense_list.html", {
        "expenses": page_obj,
        "page_obj": page_obj,
        "statuses": statuses,
        "status_filter": status_filter,
        "date_from": date_from,
        "date_to": date_to,
        "keyword": keyword,
        "progress_by_doc": progress_by_doc,
    })


@login_required
def expense_csv(request):
    """経費申請一覧のCSVエクスポート（フィルター条件を引き継ぐ）"""
    qs = T_Document.objects.filter(man_number=request.user).select_related(
        'status_cd', 'document_type', 'bumon_cd'
    ).prefetch_related('contents').order_by("-created_at")

    status_filter = request.GET.get('status', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    keyword = request.GET.get('keyword', '')

    if status_filter:
        qs = qs.filter(status_cd__status_cd=status_filter)
    qs = _apply_created_at_date_range(qs, date_from, date_to)
    if keyword:
        qs = qs.filter(
            Q(title__icontains=keyword) |
            Q(contents__purpose__icontains=keyword) |
            Q(contents__shiharaisaki__icontains=keyword) |
            Q(memo__icontains=keyword)
        ).distinct()

    response = HttpResponse(content_type='text/csv; charset=utf-8-sig')
    response['Content-Disposition'] = 'attachment; filename="expenses.csv"'
    writer = csv.writer(response)
    writer.writerow(['申請ID', '申請種別', '申請日時', '目的', '負担部門', '合計金額', '通貨', 'ステータス', '備考'])
    for exp in qs:
        first_content = exp.contents.first()
        writer.writerow([
            exp.document_id,
            exp.document_type.document_type_name if exp.document_type else '',
            timezone.localtime(exp.created_at).strftime('%Y/%m/%d %H:%M'),
            first_content.purpose if first_content else '',
            exp.bumon_cd.bumon_name if exp.bumon_cd else '',
            exp.total_amount,
            exp.tsuka_cd or '',
            exp.status_cd.status_name if exp.status_cd else '',
            exp.memo or '',
        ])
    return response

@login_required
def expense_detail(request, pk):
    expense = get_object_or_404(T_Document, pk=pk)
    
    # 取り消し処理
    if request.method == "POST" and "cancel_expense" in request.POST:
        if expense.man_number == request.user and expense.status_cd.status_cd == "INPRO":
            # ステータスを「取り消し」に変更
            try:
                cancelled_status = M_Status.objects.get(status_cd="CANCEL")
                expense.status_cd = cancelled_status
                expense.save()

                # ワークフローアクションに記録
                try:
                    from .models import T_WorkflowInstance, T_WorkflowAction
                    instance = T_WorkflowInstance.objects.filter(document_id=expense).order_by('-started_at').first()
                    if instance:
                        T_WorkflowAction.objects.create(
                            instance=instance,
                            step=instance.step,
                            approver_man_number=request.user,
                            action_status=cancelled_status,
                            comment="申請者による取り消し",
                        )
                except Exception:
                    pass

                return redirect('expenses:expense_list')
            except M_Status.DoesNotExist:
                # 取り消しステータスが存在しない場合は作成
                cancelled_status = M_Status.objects.create(
                    status_cd="CANCEL",
                    status_name="取り下げ",
                    action_name="取消し",
                )
                expense.status_cd = cancelled_status
                expense.save()

                try:
                    from .models import T_WorkflowInstance, T_WorkflowAction
                    instance = T_WorkflowInstance.objects.filter(document_id=expense).order_by('-started_at').first()
                    if instance:
                        T_WorkflowAction.objects.create(
                            instance=instance,
                            step=instance.step,
                            approver_man_number=request.user,
                            action_status=cancelled_status,
                            comment="申請者による取り消し",
                        )
                except Exception:
                    pass

                return redirect('expenses:expense_list')
        else:
            # 権限がない場合や既に処理済みの場合
            return render(request, "expenses/expense_detail.html", {
                "expense": expense,
                "error_message": "この申請は取り消しできません。"
            })
    
    # ワークフロー履歴を取得
    workflow_actions = []
    try:
        from .models import T_WorkflowAction
        workflow_actions = (
            T_WorkflowAction.objects
            .filter(instance__document_id=expense)
            .select_related('action_status', 'approver_man_number', 'step', 'instance')
            .order_by('actioned_at')
        )
    except Exception:
        workflow_actions = []

    # 承認予定者を取得（未承認 = pending/draft + 未処理の keiri ステップ）
    try:
        pending_approvers = get_pending_approvers(expense)
    except Exception:
        pending_approvers = []

    # 通貨名の解決（表示用）
    currency_name = None
    try:
        if expense.tsuka_cd:
            cur = M_Item.objects.filter(data_kbn='CUR', key=expense.tsuka_cd).first()
            if cur:
                # 表示は content2 を優先、未設定時は content をフォールバック
                currency_name = (cur.content2 or '').strip() or cur.content
    except Exception:
        currency_name = None

    dynamic_fields_display = _build_dynamic_fields_display(expense)

    progress = _get_step_progress_map([expense.document_id]).get(expense.document_id)

    is_travel = _is_travel_doc_type(expense.document_type)
    travel_route_details = []
    travel_accom_details = []
    travel_allow_details = []
    if is_travel:
        _all_details = list(expense.details.prefetch_related('attachments'))
        travel_route_details = [d for d in _all_details if isinstance(d.content, dict) and 'departure' in d.content]
        travel_accom_details = [d for d in _all_details if isinstance(d.content, dict) and d.content.get('row_type') == 'accommodation']
        travel_allow_details = [d for d in _all_details if isinstance(d.content, dict) and d.content.get('row_type') == 'allowance']

    return render(request, "expenses/expense_detail.html", {
        "expense": expense,
        "workflow_actions": workflow_actions,
        "pending_approvers": pending_approvers,
        "currency_name": currency_name,
        "dynamic_fields_display": dynamic_fields_display,
        "progress": progress,
        "is_travel": is_travel,
        "travel_route_details": travel_route_details,
        "travel_accom_details": travel_accom_details,
        "travel_allow_details": travel_allow_details,
    })

@login_required
def expense_edit(request, pk):
    expense = get_object_or_404(T_Document, pk=pk)
    
    # 権限チェック：申請者のみ編集可能
    #   編集可能ステータス: 申請中(INPRO) / 下書き(DRAFT) / 差戻し(RETURNED)
    if expense.man_number != request.user or expense.status_cd.status_cd not in ("INPRO", "DRAFT", "RETURNED"):
        return redirect('expenses:expense_detail', pk=pk)
    
    # エラーメッセージの初期化（未定義参照を防ぐ）
    error_message = None
    
    # DocType=4 の動的フィールド（編集用）を準備
    dynamic_fields = []
    try:
        doc_type_for_dyn = getattr(expense, 'document_type', None)
        if _has_dynamic_fields(doc_type_for_dyn):
            # 既存の（先頭明細の）content を初期値として取り出す
            try:
                first_detail = expense.contents.order_by('document_detail_id').first()
                existing_dyn = first_detail.content if (first_detail and isinstance(first_detail.content, dict)) else {}
            except Exception:
                existing_dyn = {}
            _dyn_dt = _resolve_dynamic_fields_doc_type(doc_type_for_dyn)
            defs = M_DocumentField.objects.filter(document_type=_dyn_dt).order_by('field_order', 'field_name')
            for d in defs:
                raw_type = (d.field_type or '').strip().lower()
                html_type = 'text'
                options = []
                if raw_type.startswith('select'):
                    html_type = 'select'
                    parts = raw_type.split(':', 1)
                    if len(parts) == 2 and parts[1]:
                        kbn = parts[1].strip()
                        # data_kbn の大小文字差異や余分な空白を吸収
                        options = list(
                            M_Item.objects.filter(data_kbn__iexact=kbn).order_by('key').values('key', 'content')
                        )
                elif raw_type in ('text', 'number', 'date'):
                    html_type = raw_type
                elif raw_type == 'num':
                    html_type = 'number'
                elif raw_type == 'label':
                    html_type = 'label'
                else:
                    html_type = 'text'
                # POST 優先、なければ既存JSON
                val = ''
                try:
                    if request.method == 'POST':
                        val = (request.POST.get(f"dyn_{d.field_name}") or '').strip()
                    if not val:
                        val = existing_dyn.get(d.field_name, '')
                except Exception:
                    val = existing_dyn.get(d.field_name, '')
                dynamic_fields.append({
                    'name':          d.field_name,
                    'label':         (d.field_name_view or d.field_name),
                    'type':          html_type,
                    'options':       options,
                    'value':         val,
                    'col_width':     d.col_width or 4,
                    'row_break':     d.row_break,
                    'required':      d.required,
                    'placeholder':   d.placeholder or '',
                    'field_help_text': d.field_help_text or '',
                    'calc_formula':  d.calc_formula or '',
                    'section_header': d.section_header or '',
                })
    except Exception:
        dynamic_fields = []

    if request.method == "POST":
        action = request.POST.get('action') or 'save'  # 'save' or 'submit'
        is_draft_edit = (action in ('draft', 'save'))
        error_message = None  # 初期化
        _aq_edit = _get_account_queryset(getattr(expense, 'document_type', None))
        _edit_doc_type_post = getattr(expense, 'document_type', None)
        expense_formset = None

        # 明細削除IDをformset初期化より先に取得し、querysetとINITIAL_FORMSから除外する。
        # これにより、削除対象行はformsetの処理対象外となり、再作成されることがない。
        delete_detail_ids = [int(x) for x in request.POST.getlist('delete_details') if x.isdigit()]

        accom_formset = None
        allow_formset = None
        tra_items_edit = M_Item.objects.filter(data_kbn='TRA').order_by('key')
        if _is_travel_doc_type(_edit_doc_type_post):
            _travel_qs = expense.contents.filter(content__has_key='departure')
            if delete_detail_ids:
                _travel_qs = _travel_qs.exclude(document_detail_id__in=delete_detail_ids)
            _post_fs = request.POST
            if delete_detail_ids:
                # INITIAL_FORMSをquerysetの実件数に揃えて整合性を保つ
                _post_fs = request.POST.copy()
                _post_fs['travel-INITIAL_FORMS'] = str(_travel_qs.count())
                # 宿泊費・日当の INITIAL_FORMS も調整
                _accom_qs_cnt = expense.contents.filter(content__row_type='accommodation').exclude(document_detail_id__in=delete_detail_ids).count()
                _allow_qs_cnt = expense.contents.filter(content__row_type='allowance').exclude(document_detail_id__in=delete_detail_ids).count()
                _post_fs['accom-INITIAL_FORMS'] = str(_accom_qs_cnt)
                _post_fs['allow-INITIAL_FORMS'] = str(_allow_qs_cnt)
            formset = TravelDetailEditFormSet(_post_fs, request.FILES, queryset=_travel_qs, prefix='travel', is_draft=is_draft_edit)
            # 宿泊費フォームセット
            _accom_qs = expense.contents.filter(content__row_type='accommodation')
            if delete_detail_ids:
                _accom_qs = _accom_qs.exclude(document_detail_id__in=delete_detail_ids)
            accom_formset = AccommodationEditFormSet(_post_fs, request.FILES, queryset=_accom_qs, prefix='accom', is_draft=is_draft_edit)
            # 日当フォームセット
            _allow_qs = expense.contents.filter(content__row_type='allowance')
            if delete_detail_ids:
                _allow_qs = _allow_qs.exclude(document_detail_id__in=delete_detail_ids)
            allow_formset = AllowanceEditFormSet(_post_fs, request.FILES, queryset=_allow_qs, prefix='allow', tra_items=tra_items_edit)
        else:
            _contents_qs = expense.contents.all()
            if delete_detail_ids:
                _contents_qs = _contents_qs.exclude(document_detail_id__in=delete_detail_ids)
            _post_fs = request.POST
            if delete_detail_ids:
                _post_fs = request.POST.copy()
                _post_fs['form-INITIAL_FORMS'] = str(_contents_qs.count())
            formset = ExpenseDetailEditFormSet(_post_fs, request.FILES, queryset=_contents_qs, account_queryset=_aq_edit, is_draft=is_draft_edit)
        
        # 通貨コードの検証
        tsuka_cd = (request.POST.get('tsuka_cd') or '').strip()
        # デフォルト: 未指定時は '00'（存在する場合）
        if not tsuka_cd:
            if M_Item.objects.filter(data_kbn='CUR', key='00').exists():
                tsuka_cd = '00'
            else:
                tsuka_cd = None
        currency_valid = True
        if tsuka_cd:
            currency_valid = M_Item.objects.filter(data_kbn='CUR', key=tsuka_cd).exists()

        # 負担部門のチェック（申請時のみ必須）
        bumon_cd_val_edit = request.POST.get('bumon_cd')
        bumon_error_edit = not is_draft_edit and not bumon_cd_val_edit
        if bumon_error_edit:
            error_message = "負担部門を選択してください。"

        # 出張件名チェック（出張旅費精算・申請時のみ必須）
        trip_title_error_edit = False
        if not is_draft_edit and _is_travel_doc_type(_edit_doc_type_post):
            _trip_title_val = (request.POST.get('trip_title') or '').strip()
            if not _trip_title_val:
                trip_title_error_edit = True
                error_message = "出張件名を入力してください。"

        # 移動経路明細：最低1行 & 各行の日付チェック（申請時のみ）
        travel_row_error_edit = False
        if not is_draft_edit and _is_travel_doc_type(_edit_doc_type_post) and not trip_title_error_edit:
            _travel_valid_count = 0
            _travel_no_date_rows = []
            try:
                _total_travel = int(request.POST.get('travel-TOTAL_FORMS', 0))
                for _i in range(_total_travel):
                    _d   = request.POST.get(f'travel-{_i}-date', '').strip()
                    _dep = request.POST.get(f'travel-{_i}-departure', '').strip()
                    _arr = request.POST.get(f'travel-{_i}-arrival', '').strip()
                    _amt = request.POST.get(f'travel-{_i}-amount', '').strip()
                    if not any([_d, _dep, _arr, _amt]):
                        continue
                    if _d and _dep and _arr:
                        _travel_valid_count += 1
                    elif not _d:
                        _travel_no_date_rows.append(str(_i + 1))
            except Exception:
                pass
            if _travel_valid_count == 0:
                travel_row_error_edit = True
                error_message = "移動経路明細に日付・発地・着地を入力してください。"
            elif _travel_no_date_rows:
                travel_row_error_edit = True
                error_message = f"移動経路明細 {', '.join(_travel_no_date_rows)} 行目の日付を入力してください。"
        # 宿泊費明細：各行の日付チェック（申請時のみ）
        if not is_draft_edit and _is_travel_doc_type(_edit_doc_type_post) and not travel_row_error_edit:
            try:
                _total_accom = int(request.POST.get('accom-TOTAL_FORMS', 0))
                _accom_no_date_rows = []
                for _i in range(_total_accom):
                    _d   = request.POST.get(f'accom-{_i}-date', '').strip()
                    _amt = request.POST.get(f'accom-{_i}-amount', '').strip()
                    _shi = request.POST.get(f'accom-{_i}-shiharaisaki', '').strip()
                    if not any([_d, _amt, _shi]):
                        continue
                    if not _d:
                        _accom_no_date_rows.append(str(_i + 1))
                if _accom_no_date_rows:
                    travel_row_error_edit = True
                    error_message = f"宿泊費明細 {', '.join(_accom_no_date_rows)} 行目の日付を入力してください。"
            except Exception:
                pass

        # 承認者チェック（申請時のみ必須）
        approver_missing_edit = []
        if not is_draft_edit and not bumon_error_edit:
            try:
                edit_doc_type = getattr(expense, 'document_type', None)
                if edit_doc_type and getattr(edit_doc_type, 'workflow_template_id', None):
                    steps_for_check = steps_with_candidates(request.user, edit_doc_type.workflow_template_id)
                    for s in steps_for_check:
                        if s.get('allowed_bumon_scope') == 'keiri':
                            continue
                        if not request.POST.get(f"approver_step_{s['step_id']}"):
                            approver_missing_edit.append(str(s['step_order']))
            except Exception:
                pass
        if approver_missing_edit:
            error_message = f"承認ステップ {', '.join(approver_missing_edit)} の承認者を選択してください。"

        # 経費明細チェック（申請時のみ・出張以外）：取引日・目的・支払先・勘定科目の空白
        detail_missing_edit = []
        if not is_draft_edit and not _is_travel_doc_type(_edit_doc_type_post):
            try:
                _total_detail_e = int(request.POST.get('form-TOTAL_FORMS', 0))
                for _i in range(_total_detail_e):
                    _amt_e = request.POST.get(f'form-{_i}-amount', '').strip()
                    _dt_e = request.POST.get(f'form-{_i}-date', '').strip()
                    _purpose_e = request.POST.get(f'form-{_i}-purpose', '').strip()
                    _shi_e = request.POST.get(f'form-{_i}-shiharaisaki', '').strip()
                    _acc_e = request.POST.get(f'form-{_i}-account', '').strip()
                    if not any([_amt_e, _dt_e, _purpose_e, _shi_e, _acc_e]):
                        continue
                    _missing_fields_e = []
                    _amt_valid_e = False
                    try:
                        _amt_valid_e = float(_amt_e) > 0
                    except (ValueError, TypeError):
                        _amt_valid_e = False
                    if not _dt_e:
                        _missing_fields_e.append('取引日')
                    if not _amt_valid_e:
                        _missing_fields_e.append('金額')
                    if not _purpose_e:
                        _missing_fields_e.append('目的')
                    if not _shi_e:
                        _missing_fields_e.append('支払先')
                    if not _acc_e:
                        _missing_fields_e.append('勘定科目')
                    if _missing_fields_e:
                        detail_missing_edit.append(f"明細{_i + 1}（{ '・'.join(_missing_fields_e) }）")
            except Exception:
                pass
        if detail_missing_edit:
            error_message = f"経費明細の入力漏れがあります: { ' / '.join(detail_missing_edit) } を入力してください。"

        _expense_fs_valid = expense_formset is None or expense_formset.is_valid()
        if formset.is_valid() and _expense_fs_valid and currency_valid and not bumon_error_edit and not approver_missing_edit and not trip_title_error_edit and not travel_row_error_edit and not detail_missing_edit:
            try:
                # 申請情報（備考・負担部門の更新）
                memo = request.POST.get('memo')
                if memo is not None:
                    expense.memo = memo[:200]
                bumon_cd_val = bumon_cd_val_edit
                if bumon_cd_val:
                    try:
                        expense.bumon_cd = M_Bumon.objects.get(bumon_cd=bumon_cd_val)
                    except M_Bumon.DoesNotExist:
                        pass
                # 通貨の更新
                expense.tsuka_cd = tsuka_cd
                # 精算方法の更新
                _pay_kbn_edit = (request.POST.get('pay_kbn') or '').strip()
                expense.pay_kbn = _pay_kbn_edit or None
                # 稟議No（全 DocType 共通で反映）
                try:
                    expense.ringi_no = (request.POST.get('ringi_no') or '').strip() or None
                except Exception:
                    pass
                # DocType=5（出張旅費精算）: 出張件名の更新
                if _is_travel_doc_type(getattr(expense, 'document_type', None)):
                    trip_title = (request.POST.get('trip_title') or '').strip()
                    if trip_title:
                        expense.title = trip_title
                # 承認者設定はワークフロー側に委ねるためここでは扱わない

                # モデル検証（pay_kbn の妥当性など）
                try:
                    expense.full_clean()
                except Exception:
                    pass

                expense.save()

                # 既存の明細は更新、新規は追加、削除指定の添付/明細を処理
                from .models import T_DocumentAttachment, T_DocumentContent
                # 1) 添付の削除（チェックされたもの）
                delete_ids = set(request.POST.getlist('delete_attachments'))
                if delete_ids:
                    T_DocumentAttachment.objects.filter(attachment_id__in=delete_ids).delete()

                # 1.5) 明細の削除（クライアントで隠され、delete_details に入っている既存ID）
                # delete_detail_ids は POST受信直後にformset初期化前で取得済み
                if delete_detail_ids:
                    # 先に添付を削除してから明細行を削除
                    T_DocumentAttachment.objects.filter(detail_id__in=delete_detail_ids).delete()
                    T_DocumentContent.objects.filter(document_detail_id__in=delete_detail_ids, document=expense).delete()

                # 動的フィールドの取り出し（DocType=4 のみ）
                dynamic_values = {}
                try:
                    if dynamic_fields:
                        for f in dynamic_fields:
                            key = f"dyn_{f['name']}"
                            val = request.POST.get(key)
                            if val is not None and val != '':
                                dynamic_values[f['name']] = val
                except Exception:
                    dynamic_values = {}

                # 2) 明細の保存（フォームセットの各行）
                # 出張旅費の場合は勘定科目670・目的を強制セット
                _edit_doc_type_obj = getattr(expense, 'document_type', None)
                _is_travel_save = _is_travel_doc_type(_edit_doc_type_obj)
                _account_670 = None
                if _is_travel_save:
                    try:
                        _account_670 = M_Account.objects.get(account_cd='670')
                    except M_Account.DoesNotExist:
                        pass
                _is_lon_save = _is_lon_doc_type(_edit_doc_type_obj)
                _account_13700 = None
                if _is_lon_save:
                    try:
                        _account_13700 = M_Account.objects.get(account_cd='13700')
                    except M_Account.DoesNotExist:
                        pass
                used_dynamic = False
                for form in formset.forms:
                    if not (form.is_valid() and form.cleaned_data):
                        continue
                    detail = form.save(commit=False)
                    detail.document = expense
                    # 既存 or 新規の区別（hidden の id で判定）
                    instance_id = form.cleaned_data.get('id') or getattr(form.instance, 'pk', None)
                    # 削除対象に含まれている既存行はスキップ
                    if instance_id and isinstance(instance_id, T_DocumentContent) and instance_id.pk in delete_detail_ids:
                        continue
                    if instance_id:
                        # 既存更新
                        detail.document_detail_id = instance_id.document_detail_id if hasattr(instance_id, 'document_detail_id') else instance_id
                    # DocType=4 の動的値は最初の明細の content に保存（1回のみ）
                    try:
                        doc_type_local = getattr(expense, 'document_type', None)
                        if _has_dynamic_fields(doc_type_local) and not used_dynamic:
                            existing = detail.content if getattr(detail, 'content', None) else {}
                            if isinstance(existing, dict):
                                existing.update(dynamic_values)
                                detail.content = existing
                            else:
                                detail.content = dynamic_values or {}
                            used_dynamic = True
                    except Exception:
                        pass

                    # 出張旅費: 勘定科目・目的を強制セット
                    if _is_travel_save:
                        if _account_670:
                            detail.account = _account_670
                        detail.purpose = '出張旅費'
                    # 前借証: 勘定科目を13700に強制セット
                    if _is_lon_save and _account_13700:
                        detail.account = _account_13700

                    detail.save()
                    # 3) 添付の追加（新規に指定されたファイル分）
                    try:
                        files = request.FILES.getlist(f"{form.prefix}-receipt")
                        file_field = form.cleaned_data.get('receipt')
                        if not files and file_field:
                            files = [file_field]
                        for f in files:
                            if not f:
                                continue
                            T_DocumentAttachment.objects.create(detail=detail, file=f)
                    except Exception:
                        pass

                    # 4) Cloud領収書の取り込み（連番指定）
                    try:
                        raw_cloud = form.cleaned_data.get('cloud_receipts')
                        for token in parse_cloud_receipt_tokens(raw_cloud):
                            seq = normalize_seq(token)
                            if not seq:
                                raise CloudReceiptFetchError(
                                    f"Cloud領収書の指定が不正です: '{token}'（例: 000123）"
                                )
                            cf = fetch_receipt_by_seq(seq)
                            att = T_DocumentAttachment(detail=detail)
                            att.file.save(cf.filename, ContentFile(cf.data), save=True)
                    except CloudReceiptFetchError:
                        raise
                    except Exception:
                        # 取得失敗はユーザーに見せるため上位で捕捉
                        raise

                    # 5) モバイルQRアップロードID経由の取り込み
                    try:
                        mobile_upload_id = (form.cleaned_data.get('mobile_upload_id') or '').strip()
                        if mobile_upload_id:
                            mobile_files = fetch_receipts_by_upload_id(mobile_upload_id)
                            for cf in mobile_files:
                                att = T_DocumentAttachment(detail=detail)
                                att.file.save(cf.filename, ContentFile(cf.data), save=True)
                    except CloudReceiptFetchError:
                        raise
                    except Exception:
                        raise

                # 宿泊費・日当の保存
                if _is_travel_save and accom_formset and accom_formset.is_valid():
                    for aform in accom_formset.forms:
                        if not (aform.is_valid() and aform.cleaned_data):
                            continue
                        # 日付・金額・支払先のいずれも未入力なら空行とみなしてスキップ
                        cd = aform.cleaned_data
                        if not cd.get('date') and not cd.get('amount') and not (cd.get('shiharaisaki') or '').strip():
                            continue
                        adetail = aform.save(commit=False)
                        adetail.document = expense
                        if _account_670:
                            adetail.account = _account_670
                        adetail.purpose = '宿泊費'
                        adetail.save()
                        # ファイルアップロード（直接）
                        try:
                            afiles = request.FILES.getlist(f"{aform.prefix}-receipt")
                            afile_field = aform.cleaned_data.get('receipt')
                            if not afiles and afile_field:
                                afiles = [afile_field]
                            for af in afiles:
                                if af:
                                    T_DocumentAttachment.objects.create(detail=adetail, file=af)
                        except Exception as e:
                            print(f"[WARN] accom receipt save error (edit): {e}", flush=True)
                        # Cloud領収書（連番指定）
                        try:
                            raw_cloud = aform.cleaned_data.get('cloud_receipts')
                            for token in parse_cloud_receipt_tokens(raw_cloud):
                                seq = normalize_seq(token)
                                if not seq:
                                    raise CloudReceiptFetchError(
                                        f"Cloud領収書の指定が不正です: '{token}'（例: 000123）"
                                    )
                                cf = fetch_receipt_by_seq(seq)
                                att = T_DocumentAttachment(detail=adetail)
                                att.file.save(cf.filename, ContentFile(cf.data), save=True)
                        except CloudReceiptFetchError:
                            raise
                        except Exception as e:
                            print(f"[WARN] accom cloud receipt error (edit): {e}", flush=True)
                        # モバイルQRアップロードID経由
                        try:
                            mobile_upload_id = (aform.cleaned_data.get('mobile_upload_id') or '').strip()
                            if mobile_upload_id:
                                mobile_files = fetch_receipts_by_upload_id(mobile_upload_id)
                                for cf in mobile_files:
                                    att = T_DocumentAttachment(detail=adetail)
                                    att.file.save(cf.filename, ContentFile(cf.data), save=True)
                        except CloudReceiptFetchError:
                            raise
                        except Exception as e:
                            print(f"[WARN] accom mobile upload error (edit): {e}", flush=True)

                if _is_travel_save and allow_formset and allow_formset.is_valid():
                    for alform in allow_formset.forms:
                        if not (alform.is_valid() and alform.cleaned_data):
                            continue
                        # 単価キー・日数のどちらも未入力なら空行とみなしてスキップ
                        cd = alform.cleaned_data
                        if not cd.get('unit_price_key') and not cd.get('days') and not cd.get('amount'):
                            continue
                        aldetail = alform.save(commit=False)
                        aldetail.document = expense
                        if _account_670:
                            aldetail.account = _account_670
                        aldetail.purpose = '日当'
                        aldetail.save()

                # 提出ボタン押下時は INPRO へ状態遷移し、ワークフローを生成
                if action == 'submit':
                    # ステータスを INPRO に
                    try:
                        sub_status = M_Status.objects.get(status_cd="INPRO")
                    except M_Status.DoesNotExist:
                        sub_status = M_Status.objects.create(status_cd="INPRO", status_name="申請中", action_name="提出")
                    expense.status_cd = sub_status
                    expense.save()

                    # 既にインスタンスがなければ作成
                    try:
                        from .models import T_WorkflowInstance, T_DocumentApprover, M_WorkflowStep, M_User, T_WorkflowAction
                        doc_type = expense.document_type
                        existing_instance = T_WorkflowInstance.objects.filter(document_id=expense).order_by('-started_at').first()
                        exists_instance = existing_instance is not None
                        # 下書きのみ（DRAFT）のインスタンスは初回申請として扱う
                        is_draft_only_instance = exists_instance and not T_WorkflowInstance.objects.filter(
                            document_id=expense
                        ).exclude(status__status_cd='DRAFT').exists()
                        if doc_type and doc_type.workflow_template_id and (not exists_instance or is_draft_only_instance):
                            wf = doc_type.workflow_template_id
                            steps = steps_with_candidates(request.user, wf)
                            # 最初のステップを現在ステップに設定
                            first_step = None
                            if steps:
                                try:
                                    first_step = M_WorkflowStep.objects.get(pk=steps[0]['step_id'])
                                except M_WorkflowStep.DoesNotExist:
                                    first_step = None
                            # ワークフロー進行中ステータスを取得/作成
                            # インスタンス自体の状態は INPRO と同義の進行とみなす
                            wf_status = sub_status
                            # DRAインスタンスが既にある場合は更新、なければ新規作成
                            if is_draft_only_instance and existing_instance:
                                existing_instance.status = wf_status
                                existing_instance.step = first_step
                                existing_instance.step_order = (steps[0]['step_order'] if steps else None)
                                existing_instance.save()
                                instance = existing_instance
                            else:
                                instance = T_WorkflowInstance.objects.create(
                                    document_id=expense,
                                    workflow_template=wf,
                                    status=wf_status,
                                    step=first_step,
                                    step_order=(steps[0]['step_order'] if steps else None),
                                )
                            # SUB の履歴を記録
                            try:
                                T_WorkflowAction.objects.create(
                                    instance=instance,
                                    step=first_step,
                                    approver_man_number=request.user,
                                    action_status=sub_status,
                                    comment="申請者による提出",
                                )
                            except Exception:
                                pass
                            # 経理ステップは自動回付、それ以外はフォームの選択値を保存
                            for s in steps:
                                if s.get('allowed_bumon_scope') == 'keiri' and s.get('candidates'):
                                    try:
                                        step_obj = M_WorkflowStep.objects.get(pk=s['step_id'])
                                        man = s['candidates'][0]['man_number']
                                        approver_user = M_User.objects.get(man_number=man)
                                        T_DocumentApprover.objects.create(
                                            document_id=expense,
                                            step_id=step_obj,
                                            man_number=approver_user,
                                            step_order=s['step_order'],
                                            status='pending'
                                        )
                                    except Exception:
                                        pass
                                elif s.get('allowed_bumon_scope') != 'keiri':
                                    # 非経理ステップはフォームの選択値を保存
                                    selected = request.POST.get(f"approver_step_{s['step_id']}")
                                    if selected:
                                        try:
                                            step_obj = M_WorkflowStep.objects.get(pk=s['step_id'])
                                            approver_user = M_User.objects.get(man_number=selected)
                                            T_DocumentApprover.objects.create(
                                                document_id=expense,
                                                step_id=step_obj,
                                                man_number=approver_user,
                                                step_order=s['step_order'],
                                                status='pending'
                                            )
                                        except Exception:
                                            pass
                            # 最初のステップの承認者に通知メールを送信
                            try:
                                if first_step:
                                    next_approvers = T_DocumentApprover.objects.filter(
                                        document_id=expense,
                                        step_id=first_step,
                                        step_order=getattr(first_step, 'step_order', None),
                                    )
                                    subject, body = _build_approval_request_mail(expense)
                                    if next_approvers.exists():
                                        for a in next_approvers:
                                            to_addr = getattr(getattr(a.man_number, 'email', None), 'strip', lambda: None)()
                                            send_notification(to_addr, subject, body)
                            except Exception:
                                pass
                        elif exists_instance and not is_draft_only_instance:
                            # 既存インスタンスがある場合も SUB を履歴に記録し、承認者を更新して通知
                            try:
                                instance = T_WorkflowInstance.objects.filter(document_id=expense).order_by('-started_at').first()
                                if instance:
                                    T_WorkflowAction.objects.create(
                                        instance=instance,
                                        step=instance.step,
                                        approver_man_number=request.user,
                                        action_status=sub_status,
                                        comment="申請者による再提出",
                                    )
                                    # 承認者を更新（既存レコードを削除して再登録）
                                    wf = doc_type.workflow_template_id if doc_type else None
                                    if wf:
                                        re_steps = steps_with_candidates(request.user, wf)
                                        # 非経理ステップの既存承認者を削除して再登録
                                        for s in re_steps:
                                            try:
                                                step_obj = M_WorkflowStep.objects.get(pk=s['step_id'])
                                                if s.get('allowed_bumon_scope') == 'keiri':
                                                    continue
                                                T_DocumentApprover.objects.filter(
                                                    document_id=expense, step_id=step_obj
                                                ).delete()
                                                selected = request.POST.get(f"approver_step_{s['step_id']}")
                                                if selected:
                                                    approver_user = M_User.objects.get(man_number=selected)
                                                    T_DocumentApprover.objects.create(
                                                        document_id=expense,
                                                        step_id=step_obj,
                                                        man_number=approver_user,
                                                        step_order=s['step_order'],
                                                        status='pending'
                                                    )
                                            except Exception:
                                                pass
                                        # 最初のステップを特定して通知
                                        first_step_re = None
                                        if re_steps:
                                            try:
                                                first_step_re = M_WorkflowStep.objects.get(pk=re_steps[0]['step_id'])
                                            except Exception:
                                                pass
                                        if first_step_re:
                                            next_approvers_re = T_DocumentApprover.objects.filter(
                                                document_id=expense,
                                                step_id=first_step_re,
                                                step_order=getattr(first_step_re, 'step_order', None),
                                            )
                                            subject, body = _build_approval_request_mail(expense, "【再申請】")
                                            if next_approvers_re.exists():
                                                for a in next_approvers_re:
                                                    to_addr = getattr(getattr(a.man_number, 'email', None), 'strip', lambda: None)()
                                                    send_notification(to_addr, subject, body)
                            except Exception:
                                pass
                    except Exception as e:
                        print("Workflow create on edit error:", str(e))

                return redirect('expenses:expense_detail', pk=pk)
            except Exception as e:
                print("Edit error:", str(e))
                error_message = f"編集中にエラーが発生しました: {str(e)}"
        else:
            # バリデーションエラー時のメッセージ（既にセット済みの場合は上書きしない）
            if not error_message:
                if not currency_valid:
                    error_message = "通貨の選択が不正です。"
                else:
                    error_message = "入力内容にエラーがあります。各明細のエラーメッセージを確認してください。"
    else:
        _aq_edit = _get_account_queryset(getattr(expense, 'document_type', None))
        _edit_doc_type_get = getattr(expense, 'document_type', None)
        expense_formset = None
        accom_formset = None
        allow_formset = None
        tra_items_edit = M_Item.objects.filter(data_kbn='TRA').order_by('key')
        if _is_travel_doc_type(_edit_doc_type_get):
            _travel_qs = expense.contents.filter(content__has_key='departure')
            # 下書き等で明細が1件もない場合は空フォームを1件表示（追加ボタンの複製元）
            if not _travel_qs.exists():
                from django.forms import modelformset_factory as _mff
                from .forms import TravelDetailForm as _TDF
                from .models import T_DocumentContent as _TDC
                _TempFS = _mff(_TDC, form=_TDF, extra=1, can_delete=False, max_num=20)
                formset = _TempFS(queryset=_TDC.objects.none(), prefix='travel')
            else:
                formset = TravelDetailEditFormSet(queryset=_travel_qs, prefix='travel')
            # 宿泊費フォームセット（GET）
            _accom_qs = expense.contents.filter(content__row_type='accommodation')
            accom_formset = AccommodationEditFormSet(queryset=_accom_qs, prefix='accom')
            # 日当フォームセット（GET）
            _allow_qs = expense.contents.filter(content__row_type='allowance')
            allow_formset = AllowanceEditFormSet(queryset=_allow_qs, prefix='allow', tra_items=tra_items_edit)
        else:
            _qs = expense.contents.all()
            if not _qs.exists():
                from django.forms import modelformset_factory as _mff
                from .forms import ExpenseDetailForm as _EDF, BaseExpenseDetailFormSet as _BEFS
                from .models import T_DocumentContent as _TDC
                _TempFS = _mff(
                    _TDC, form=_EDF, formset=_BEFS,
                    extra=1, can_delete=False, min_num=0, max_num=10,
                )
                formset = _TempFS(queryset=_TDC.objects.none(), account_queryset=_aq_edit)
            else:
                formset = ExpenseDetailEditFormSet(queryset=_qs, account_queryset=_aq_edit)
        error_message = None
    
    # 申請情報のドロップダウン用データ
    groups = M_Group.objects.all().order_by('group_cd')
    _edit_doc_type = getattr(expense, 'document_type', None)
    bumons = _get_bumons_for_user(request.user, _edit_doc_type)
    pay_items = M_Item.objects.filter(data_kbn='pay').order_by('key')
    currencies = M_Item.objects.filter(data_kbn='CUR').order_by('key')

    # 承認候補 UI 用データ（GET/POST で同じ構造を出す）
    workflow_steps = []
    try:
        doc_type = expense.document_type
        if doc_type and doc_type.workflow_template_id:
            workflow_steps = steps_with_candidates(request.user, doc_type.workflow_template_id)
    except Exception:
        workflow_steps = []

    # ドラフトで保存済みの承認者選択があればプリセレクト
    if workflow_steps:
        # 既存のドラフト承認者（または pending）を拾ってステップごとに選択値へ
        from .models import T_DocumentApprover, M_BelongTo, M_User
        existing = T_DocumentApprover.objects.filter(document_id=expense)
        selected_map = {}
        for a in existing:
            # 外部キーの参照先が削除済みでも落ちないように raw FK 値で参照
            try:
                step_pk = getattr(a, 'step_id_id', None)
            except Exception:
                step_pk = None
            if step_pk is None:
                # 可能なら関連を辿る（存在しない場合はスキップ）
                try:
                    step_pk = getattr(getattr(a, 'step_id', None), 'step_id', None)
                except Exception:
                    step_pk = None
            # 後勝ちでOK（同一ステップ複数は想定しない）
            selected_map[step_pk] = getattr(a.man_number, 'man_number', None)
        # POST の場合は POST 値を優先
        for s in workflow_steps:
            key = f"approver_step_{s['step_id']}"
            if request.method == 'POST':
                s['selected'] = request.POST.get(key, '')
            else:
                s['selected'] = selected_map.get(s['step_id'], '') or ''
        # 'others' 用に選択ユーザーの所属グループを推定してプリセット
        for s in workflow_steps:
            try:
                if s.get('allowed_bumon_scope') == 'others' and s.get('selected'):
                    man = s['selected']
                    # ユーザーの所属（最初のもの）を採用
                    grp = (
                        M_BelongTo.objects
                        .filter(man_number__man_number=man)
                        .values_list('group_cd__group_cd', flat=True)
                        .first()
                    )
                    if grp:
                        s['selected_group_cd'] = grp
            except Exception:
                pass

    # 差し戻し・却下コメントを取得（2-8）
    latest_return_action = None
    try:
        from .models import T_WorkflowAction
        latest_return_action = (
            T_WorkflowAction.objects
            .filter(
                instance__document_id=expense,
                action_status__status_cd__in=['RETURNED', 'REJECTED'],
            )
            .select_related('action_status', 'approver_man_number')
            .order_by('-actioned_at')
            .first()
        )
    except Exception:
        latest_return_action = None

    _edit_template = (
        "expenses/travel_expense_form.html"
        if _is_travel_doc_type(getattr(expense, 'document_type', None))
        else "expenses/expense_edit.html"
    )
    return render(request, _edit_template, {
        "formset": formset,
        "expense_formset": expense_formset,
        "accom_formset": accom_formset,
        "allow_formset": allow_formset,
        "tra_items": tra_items_edit if _is_travel_doc_type(getattr(expense, 'document_type', None)) else [],
        "expense": expense,
        "is_edit_mode": True,
        "error_message": error_message,
        "groups": groups,
        "bumons": bumons,
        "pay_items": pay_items,
        "currencies": currencies,
        "workflow_steps": workflow_steps,
        "dynamic_fields": dynamic_fields,
        "current_bumon_cd": expense.bumon_cd.bumon_cd if expense.bumon_cd else "",
        "latest_return_action": latest_return_action,
        "current_doc_type_name": getattr(getattr(expense, 'document_type', None), 'document_type_name', None),
        "form_action": "",
        "submission_id": str(uuid.uuid4()),
        # カテゴリ別フィールド制御
        **_asset_form_context(getattr(expense, 'document_type', None)),
    })

@login_required
def expense_delete(request, pk):
    """下書き(DRA)の申請を物理削除する。申請者本人のみ、POST のみ受理。"""
    expense = get_object_or_404(T_Document, pk=pk)
    if expense.man_number != request.user:
        return redirect('expenses:expense_detail', pk=pk)
    if not (expense.status_cd and expense.status_cd.status_cd == 'DRAFT'):
        return redirect('expenses:expense_detail', pk=pk)
    if request.method != 'POST':
        return redirect('expenses:expense_edit', pk=pk)
    with transaction.atomic():
        # PROTECT 関係の依存レコードを先に削除
        instances = T_WorkflowInstance.objects.filter(document_id=expense)
        T_WorkflowAction.objects.filter(instance_id__in=instances).delete()
        instances.delete()
        T_DocumentApprover.objects.filter(document_id=expense).delete()
        # 添付→明細は CASCADE だが、GCS 等の外部リソース解放のため明示的に順序削除
        T_DocumentAttachment.objects.filter(detail__document=expense).delete()
        T_DocumentContent.objects.filter(document=expense).delete()
        expense.delete()
    return redirect('expenses:expense_list')


@login_required
def expense_create(request, document_type_id=None):
    # DocType=1(支出伺い) のワークフローテンプレートIDを確認し、初回表示時にアラート表示するためにコンテキストへ渡す
    doc1_wf_id = None
    doc1_name = None
    # 常に初期化（テンプレート参照の未定義を防ぐ）
    error_message = None
    try:
        doc1 = M_DocumentType.objects.filter(document_type_id=1).select_related('workflow_template_id').first()
        if doc1:
            doc1_wf_id = getattr(doc1, 'workflow_template_id_id', None)
            doc1_name = doc1.document_type_name
    except Exception:
        doc1_wf_id = None
        doc1_name = None
    # 動的フィールド定義（DocType=4 のみ適用）
    dynamic_fields = []
    resolved_doc_type = None
    try:
        if document_type_id:
            resolved_doc_type = M_DocumentType.objects.filter(document_type_id=document_type_id).first()
        if not resolved_doc_type:
            resolved_doc_type = M_DocumentType.objects.filter(document_type_name="経費精算書").first()
        if _has_dynamic_fields(resolved_doc_type):
            # 型マッピングと select のオプション解決。全定義をテンプレートへ渡す
            _dyn_dt_c = _resolve_dynamic_fields_doc_type(resolved_doc_type)
            defs = M_DocumentField.objects.filter(document_type=_dyn_dt_c).order_by('field_order', 'field_name')
            for d in defs:
                raw_type = (d.field_type or '').strip().lower()
                html_type = 'text'
                options = []
                if raw_type.startswith('select'):
                    html_type = 'select'
                    # 形式: select:data_kbn
                    parts = raw_type.split(':', 1)
                    if len(parts) == 2 and parts[1]:
                        kbn = parts[1].strip()
                        options = list(
                            M_Item.objects.filter(data_kbn__iexact=kbn).order_by('key').values('key', 'content')
                        )
                elif raw_type in ('text', 'number', 'date'):
                    html_type = raw_type
                elif raw_type == 'num':
                    html_type = 'number'
                elif raw_type == 'label':
                    html_type = 'label'
                else:
                    html_type = 'text'

                posted_val = ''
                try:
                    posted_val = (request.POST.get(f"dyn_{d.field_name}") or '').strip()
                except Exception:
                    posted_val = ''
                dynamic_fields.append({
                    'name':          d.field_name,
                    'label':         (d.field_name_view or d.field_name),
                    'type':          html_type,
                    'options':       options,
                    'value':         posted_val,
                    'col_width':     d.col_width or 4,
                    'row_break':     d.row_break,
                    'required':      d.required,
                    'placeholder':   d.placeholder or '',
                    'field_help_text': d.field_help_text or '',
                    'calc_formula':  d.calc_formula or '',
                    'section_header': d.section_header or '',
                })
    except Exception:
        dynamic_fields = []

    if request.method == "POST":
        # 送信アクション（申請 or 下書き）
        action = request.POST.get('action') or 'submit'
        is_draft = (action == 'draft')
        # 二重送信防止用トークン
        submission_id = request.POST.get('submission_id')
        processed = set(request.session.get('processed_submission_ids', []))
        if submission_id and submission_id in processed:
            # 既に処理済みの投稿 → 重複作成を避けてホームへ
            return redirect('expenses:home')

        # ExpenseFormは不要になったため削除
        _aq = _get_account_queryset(resolved_doc_type)
        expense_formset = None
        accom_formset = None
        allow_formset = None
        tra_items = M_Item.objects.filter(data_kbn='TRA').order_by('key')
        if _is_travel_doc_type(resolved_doc_type):
            formset = TravelDetailFormSet(request.POST, request.FILES, prefix='travel', is_draft=is_draft)
            accom_formset = AccommodationFormSet(request.POST, request.FILES, prefix='accom', is_draft=is_draft)
            allow_formset = AllowanceFormSet(request.POST, request.FILES, prefix='allow', tra_items=tra_items)
        else:
            formset = ExpenseDetailFormSet(request.POST, request.FILES, account_queryset=_aq, is_draft=is_draft)
        print("Formset is valid:", formset.is_valid())
        # 申請情報の取得
        memo = request.POST.get('memo')
        ringi_no = (request.POST.get('ringi_no') or '').strip()
        bumon_cd_val = request.POST.get('bumon_cd')
        pay_kbn = request.POST.get('pay_kbn')
        # 通貨コードの検証
        tsuka_cd = (request.POST.get('tsuka_cd') or '').strip()
        # デフォルト: 未指定時は '00'（存在する場合）
        if not tsuka_cd:
            if M_Item.objects.filter(data_kbn='CUR', key='00').exists():
                tsuka_cd = '00'
            else:
                tsuka_cd = None
        currency_valid = True
        if tsuka_cd:
            currency_valid = M_Item.objects.filter(data_kbn='CUR', key=tsuka_cd).exists()
        # 旧: 手動承認者選択は廃止（ワークフローステップで管理）

        # デバッグ用: 勘定科目の数を確認
        print("Available accounts:", M_Account.objects.count())
        if not formset.is_valid():
            print("Formset errors:", formset.errors)
            error_message = "入力内容にエラーがあります。各明細のエラーメッセージを確認してください。"

        # 負担部門のチェック（申請時のみ必須）
        bumon_required_error = not is_draft and not bumon_cd_val
        if bumon_required_error:
            error_message = "負担部門を選択してください。"

        # 出張件名チェック（出張旅費精算・申請時のみ必須）
        trip_title_error_create = False
        if not is_draft and _is_travel_doc_type(resolved_doc_type):
            _trip_title_val_c = (request.POST.get('trip_title') or '').strip()
            if not _trip_title_val_c:
                trip_title_error_create = True
                error_message = "出張件名を入力してください。"

        # 移動経路明細：最低1行 & 各行の日付チェック（申請時のみ）
        travel_row_error_create = False
        if not is_draft and _is_travel_doc_type(resolved_doc_type) and not trip_title_error_create:
            _travel_valid_count_c = 0
            _travel_no_date_rows_c = []
            try:
                _total_travel_c = int(request.POST.get('travel-TOTAL_FORMS', 0))
                for _i in range(_total_travel_c):
                    _d   = request.POST.get(f'travel-{_i}-date', '').strip()
                    _dep = request.POST.get(f'travel-{_i}-departure', '').strip()
                    _arr = request.POST.get(f'travel-{_i}-arrival', '').strip()
                    _amt = request.POST.get(f'travel-{_i}-amount', '').strip()
                    if not any([_d, _dep, _arr, _amt]):
                        continue
                    if _d and _dep and _arr:
                        _travel_valid_count_c += 1
                    elif not _d:
                        _travel_no_date_rows_c.append(str(_i + 1))
            except Exception:
                pass
            if _travel_valid_count_c == 0:
                travel_row_error_create = True
                error_message = "移動経路明細に日付・発地・着地を入力してください。"
            elif _travel_no_date_rows_c:
                travel_row_error_create = True
                error_message = f"移動経路明細 {', '.join(_travel_no_date_rows_c)} 行目の日付を入力してください。"
        # 宿泊費明細：各行の日付チェック（申請時のみ）
        if not is_draft and _is_travel_doc_type(resolved_doc_type) and not travel_row_error_create:
            try:
                _total_accom_c = int(request.POST.get('accom-TOTAL_FORMS', 0))
                _accom_no_date_rows_c = []
                for _i in range(_total_accom_c):
                    _d   = request.POST.get(f'accom-{_i}-date', '').strip()
                    _amt = request.POST.get(f'accom-{_i}-amount', '').strip()
                    _shi = request.POST.get(f'accom-{_i}-shiharaisaki', '').strip()
                    if not any([_d, _amt, _shi]):
                        continue
                    if not _d:
                        _accom_no_date_rows_c.append(str(_i + 1))
                if _accom_no_date_rows_c:
                    travel_row_error_create = True
                    error_message = f"宿泊費明細 {', '.join(_accom_no_date_rows_c)} 行目の日付を入力してください。"
            except Exception:
                pass

        # 承認者チェック（申請時のみ必須）
        approver_missing_create = []
        if not is_draft and not bumon_required_error:
            try:
                if resolved_doc_type and getattr(resolved_doc_type, 'workflow_template_id', None):
                    steps_for_check = steps_with_candidates(request.user, resolved_doc_type.workflow_template_id)
                    for s in steps_for_check:
                        if s.get('allowed_bumon_scope') == 'keiri':
                            continue
                        if not request.POST.get(f"approver_step_{s['step_id']}"):
                            approver_missing_create.append(str(s['step_order']))
            except Exception:
                pass
        if approver_missing_create:
            error_message = f"承認ステップ {', '.join(approver_missing_create)} の承認者を選択してください。"

        # 経費明細チェック（申請時のみ・出張以外）：取引日・目的・支払先・勘定科目の空白
        detail_missing_create = []
        if not is_draft and not _is_travel_doc_type(resolved_doc_type):
            try:
                _total_detail_c = int(request.POST.get('form-TOTAL_FORMS', 0))
                for _i in range(_total_detail_c):
                    _amt_c = request.POST.get(f'form-{_i}-amount', '').strip()
                    _dt_c = request.POST.get(f'form-{_i}-date', '').strip()
                    _purpose_c = request.POST.get(f'form-{_i}-purpose', '').strip()
                    _shi_c = request.POST.get(f'form-{_i}-shiharaisaki', '').strip()
                    _acc_c = request.POST.get(f'form-{_i}-account', '').strip()
                    # 完全に空の行はスキップ（入力意思なし）
                    if not any([_amt_c, _dt_c, _purpose_c, _shi_c, _acc_c]):
                        continue
                    _missing_fields = []
                    _amt_valid_c = False
                    try:
                        _amt_valid_c = float(_amt_c) > 0
                    except (ValueError, TypeError):
                        _amt_valid_c = False
                    if not _dt_c:
                        _missing_fields.append('取引日')
                    if not _amt_valid_c:
                        _missing_fields.append('金額')
                    if not _purpose_c:
                        _missing_fields.append('目的')
                    if not _shi_c:
                        _missing_fields.append('支払先')
                    if not _acc_c:
                        _missing_fields.append('勘定科目')
                    if _missing_fields:
                        detail_missing_create.append(f"明細{_i + 1}（{ '・'.join(_missing_fields) }）")
            except Exception:
                pass
        if detail_missing_create:
            error_message = f"経費明細の入力漏れがあります: { ' / '.join(detail_missing_create) } を入力してください。"

        # 動的フィールドの取り出し（DocType=4 のみ）
        dynamic_values = {}
        try:
            if dynamic_fields:
                for f in dynamic_fields:
                    key = f"dyn_{f['name']}"
                    val = request.POST.get(key)
                    if val is not None and val != '':
                        dynamic_values[f['name']] = val
        except Exception:
            dynamic_values = {}

        _expense_fs_valid = expense_formset is None or expense_formset.is_valid()
        if formset.is_valid() and _expense_fs_valid and currency_valid and not bumon_required_error and not approver_missing_create and not trip_title_error_create and not travel_row_error_create and not detail_missing_create:
            try:
                with transaction.atomic():
                    # 文書を作成
                    expense = T_Document()
                    expense.man_number = request.user
                    # ステータス（申請=INPRO／下書き=DRAFT）
                    status_code = "DRAFT" if is_draft else "INPRO"
                    try:
                        status = M_Status.objects.get(status_cd=status_code)
                    except M_Status.DoesNotExist:
                        # 存在しない場合は作成
                        default_name = "下書き" if is_draft else "申請中"
                        status = M_Status.objects.create(status_cd=status_code, status_name=default_name)
                    expense.status_cd = status
                    # 文書種別（必須）：URL引数の document_type_id があれば優先、なければ「経費精算書」を採用
                    doc_type = None
                    if document_type_id:
                        doc_type = M_DocumentType.objects.filter(document_type_id=document_type_id).first()
                    if not doc_type:
                        doc_type, _ = M_DocumentType.objects.get_or_create(
                            document_type_name="経費精算書",
                            defaults={"description": "経費申請用"}
                        )
                    expense.document_type = doc_type
                    # 備考と負担部門
                    if memo:
                        expense.memo = memo[:200]
                    if bumon_cd_val:
                        try:
                            expense.bumon_cd = M_Bumon.objects.get(bumon_cd=bumon_cd_val)
                        except M_Bumon.DoesNotExist:
                            pass
                    # 通貨
                    expense.tsuka_cd = tsuka_cd
                    # 精算方法
                    expense.pay_kbn = (pay_kbn or '').strip() or None
                    # 稟議No（全 DocType 共通で設定）
                    try:
                        expense.ringi_no = ringi_no or None
                    except Exception:
                        pass
                    # タイトル（必須）
                    if _is_travel_doc_type(resolved_doc_type or doc_type):
                        # DocType=5: フォームのtrip_titleフィールドから取得、なければ最初の経路から生成
                        title = (request.POST.get('trip_title') or '').strip()
                        if not title:
                            for f in formset.forms:
                                if f.is_valid() and f.cleaned_data:
                                    dep = f.cleaned_data.get('departure', '')
                                    arr = f.cleaned_data.get('arrival', '')
                                    if dep or arr:
                                        title = f"{dep}→{arr}" if dep and arr else (dep or arr)
                                        break
                        expense.title = title or "出張旅費精算"
                    else:
                        # 最初の明細の目的から作成、なければデフォルト
                        title = None
                        for f in formset.forms:
                            if f.is_valid() and f.cleaned_data:
                                title = f.cleaned_data.get('purpose')
                                if title:
                                    break
                        expense.title = (title or "経費申請").strip()

                    expense.save()
                    print("Document saved:", expense.document_id)

                    # 明細データを保存
                    # 出張旅費の場合は勘定科目670・目的を強制セット
                    _create_doc_type_obj = resolved_doc_type or doc_type
                    _is_travel_save_c = _is_travel_doc_type(_create_doc_type_obj)
                    _account_670_c = None
                    if _is_travel_save_c:
                        try:
                            _account_670_c = M_Account.objects.get(account_cd='670')
                        except M_Account.DoesNotExist:
                            pass
                    _is_lon_save_c = _is_lon_doc_type(_create_doc_type_obj)
                    _account_13700_c = None
                    if _is_lon_save_c:
                        try:
                            _account_13700_c = M_Account.objects.get(account_cd='13700')
                        except M_Account.DoesNotExist:
                            pass
                    used_dynamic = False
                    # POSTデータ内のmobile_upload_idを全て確認（デバッグ用）
                    for k, v in request.POST.items():
                        if 'mobile_upload_id' in k and v.strip():
                            print(f"[DEBUG] POST {k}={v}", flush=True)
                    for form in formset.forms:
                        if form.is_valid() and form.cleaned_data:
                            detail = form.save(commit=False)
                            detail.document = expense
                            # DocType=4 の動的値は最初の明細の content に保存
                            try:
                                if _has_dynamic_fields(resolved_doc_type or doc_type) and not used_dynamic:
                                    existing = detail.content if getattr(detail, 'content', None) else {}
                                    if isinstance(existing, dict):
                                        existing.update(dynamic_values)
                                        detail.content = existing
                                    else:
                                        detail.content = dynamic_values or {}
                                    used_dynamic = True
                            except Exception:
                                pass
                            # 出張旅費: 勘定科目・目的を強制セット
                            if _is_travel_save_c:
                                if _account_670_c:
                                    detail.account = _account_670_c
                                detail.purpose = '出張旅費'
                            # 前借証: 勘定科目を13700に強制セット
                            if _is_lon_save_c and _account_13700_c:
                                detail.account = _account_13700_c
                            detail.save()
                            try:
                                from .models import T_DocumentAttachment
                                files = request.FILES.getlist(f"{form.prefix}-receipt")
                                file_field = form.cleaned_data.get('receipt')
                                if not files and file_field:
                                    if isinstance(file_field, (list, tuple)):
                                        files = [f for f in file_field if f]
                                    else:
                                        files = [file_field]
                                print(f"[DEBUG] travel receipt files for {form.prefix}: {[f.name for f in files if f]}", flush=True)
                                for f in files:
                                    if not f:
                                        continue
                                    T_DocumentAttachment.objects.create(detail=detail, file=f)
                            except Exception as e:
                                print(f"[WARN] travel receipt save error: {e}", flush=True)

                            # Cloud領収書の取り込み（連番指定）
                            try:
                                from .models import T_DocumentAttachment
                                raw_cloud = form.cleaned_data.get('cloud_receipts')
                                for token in parse_cloud_receipt_tokens(raw_cloud):
                                    seq = normalize_seq(token)
                                    if not seq:
                                        raise CloudReceiptFetchError(
                                            f"Cloud領収書の指定が不正です: '{token}'（例: 000123）"
                                        )
                                    cf = fetch_receipt_by_seq(seq)
                                    att = T_DocumentAttachment(detail=detail)
                                    att.file.save(cf.filename, ContentFile(cf.data), save=True)
                            except CloudReceiptFetchError:
                                raise
                            except Exception:
                                raise

                            # モバイルQRアップロードID経由の取り込み
                            try:
                                from .models import T_DocumentAttachment
                                # form.cleaned_dataとPOSTの両方から取得を試みる
                                mobile_upload_id = (form.cleaned_data.get('mobile_upload_id') or '').strip()
                                if not mobile_upload_id:
                                    mobile_upload_id = (request.POST.get(f'{form.prefix}-mobile_upload_id') or '').strip()
                                print(f"[DEBUG] mobile_upload_id for {form.prefix}: '{mobile_upload_id}'", flush=True)
                                if mobile_upload_id:
                                    mobile_files = fetch_receipts_by_upload_id(mobile_upload_id)
                                    print(f"[DEBUG] mobile_files count: {len(mobile_files)}", flush=True)
                                    for cf in mobile_files:
                                        att = T_DocumentAttachment(detail=detail)
                                        att.file.save(cf.filename, ContentFile(cf.data), save=True)
                                        print(f"[DEBUG] saved mobile att: {cf.filename}", flush=True)
                            except CloudReceiptFetchError as e:
                                print(f"[WARN] mobile upload fetch error: {e}", flush=True)
                                raise
                            except Exception as e:
                                print(f"[WARN] mobile upload error: {e}", flush=True)
                                raise

                            print("Detail saved:", detail.document_detail_id)

                    # 宿泊費・日当の保存（新規）
                    if _is_travel_save_c and accom_formset and accom_formset.is_valid():
                        for aform in accom_formset.forms:
                            if not (aform.is_valid() and aform.cleaned_data):
                                continue
                            # 日付・金額・支払先のいずれも未入力なら空行とみなしてスキップ
                            cd = aform.cleaned_data
                            if not cd.get('date') and not cd.get('amount') and not (cd.get('shiharaisaki') or '').strip():
                                continue
                            adetail = aform.save(commit=False)
                            adetail.document = expense
                            if _account_670_c:
                                adetail.account = _account_670_c
                            adetail.purpose = '宿泊費'
                            adetail.save()
                            # ファイルアップロード（直接）
                            try:
                                from .models import T_DocumentAttachment
                                afiles = request.FILES.getlist(f"{aform.prefix}-receipt")
                                afile_field = aform.cleaned_data.get('receipt')
                                if not afiles and afile_field:
                                    afiles = [afile_field]
                                for af in afiles:
                                    if af:
                                        T_DocumentAttachment.objects.create(detail=adetail, file=af)
                            except Exception as e:
                                print(f"[WARN] accom receipt save error: {e}", flush=True)
                            # Cloud領収書（連番指定）
                            try:
                                raw_cloud = aform.cleaned_data.get('cloud_receipts')
                                for token in parse_cloud_receipt_tokens(raw_cloud):
                                    seq = normalize_seq(token)
                                    if not seq:
                                        raise CloudReceiptFetchError(
                                            f"Cloud領収書の指定が不正です: '{token}'（例: 000123）"
                                        )
                                    cf = fetch_receipt_by_seq(seq)
                                    att = T_DocumentAttachment(detail=adetail)
                                    att.file.save(cf.filename, ContentFile(cf.data), save=True)
                            except CloudReceiptFetchError:
                                raise
                            except Exception as e:
                                print(f"[WARN] accom cloud receipt error: {e}", flush=True)
                            # モバイルQRアップロードID経由
                            try:
                                mobile_upload_id = (aform.cleaned_data.get('mobile_upload_id') or '').strip()
                                if mobile_upload_id:
                                    mobile_files = fetch_receipts_by_upload_id(mobile_upload_id)
                                    for cf in mobile_files:
                                        att = T_DocumentAttachment(detail=adetail)
                                        att.file.save(cf.filename, ContentFile(cf.data), save=True)
                            except CloudReceiptFetchError:
                                raise
                            except Exception as e:
                                print(f"[WARN] accom mobile upload error: {e}", flush=True)

                    if _is_travel_save_c and allow_formset and allow_formset.is_valid():
                        for alform in allow_formset.forms:
                            if not (alform.is_valid() and alform.cleaned_data):
                                continue
                            # 単価キー・日数のどちらも未入力なら空行とみなしてスキップ
                            cd = alform.cleaned_data
                            if not cd.get('unit_price_key') and not cd.get('days') and not cd.get('amount'):
                                continue
                            aldetail = alform.save(commit=False)
                            aldetail.document = expense
                            if _account_670_c:
                                aldetail.account = _account_670_c
                            aldetail.purpose = '日当'
                            aldetail.save()

                    # 下書き時: 選択済みの承認者をドラフトとして保存
                    if is_draft and doc_type.workflow_template_id:
                        wf = doc_type.workflow_template_id
                        steps = steps_with_candidates(request.user, wf)
                        from .models import T_DocumentApprover, M_WorkflowStep, M_User
                        for s in steps:
                            step_id = s['step_id']
                            scope = s['allowed_bumon_scope']
                            selected = None
                            field_name = f"approver_step_{step_id}"

                            if scope == 'keiri':
                                # 自動候補（あれば）をドラフト保存
                                cand = s['candidates'][0] if s['candidates'] else None
                                if cand:
                                    selected = cand['man_number']
                                else:
                                    continue
                            else:
                                selected = request.POST.get(field_name) or None
                                # 下書きでは未選択も許容
                                if not selected:
                                    continue

                            valid_man_numbers = {c['man_number'] for c in s['candidates']}
                            if selected and selected in valid_man_numbers:
                                try:
                                    step_obj = M_WorkflowStep.objects.get(pk=step_id)
                                    approver_user = M_User.objects.get(man_number=selected)
                                    T_DocumentApprover.objects.create(
                                        document_id=expense,
                                        step_id=step_obj,
                                        man_number=approver_user,
                                        step_order=s['step_order'],
                                        status='draft'
                                    )
                                except Exception:
                                    pass

                        # 履歴（DRF）を記録するため、ワークフローインスタンスを作成（なければ）
                        try:
                            from .models import T_WorkflowInstance, T_WorkflowAction
                            # 先頭ステップ（存在すれば）
                            first_step = None
                            try:
                                if steps:
                                    from .models import M_WorkflowStep
                                    first_step = M_WorkflowStep.objects.get(pk=steps[0]['step_id'])
                            except Exception:
                                first_step = None
                            # インスタンス取得/作成（DRAFT 状態で保持）
                            dra_inst_status = M_Status.objects.get_or_create(status_cd="DRAFT", defaults={"status_name": "作成中", "action_name": "下書き"})[0]
                            instance = T_WorkflowInstance.objects.filter(document_id=expense).order_by('-started_at').first()
                            if not instance:
                                instance = T_WorkflowInstance.objects.create(
                                    document_id=expense,
                                    workflow_template=wf,
                                    status=dra_inst_status,
                                    step=first_step,
                                    step_order=(steps[0]['step_order'] if steps else None),
                                )
                            # アクション（DRAFT）を記録
                            dra_action_status = M_Status.objects.get_or_create(status_cd="DRAFT", defaults={"status_name": "作成中", "action_name": "下書き"})[0]
                            T_WorkflowAction.objects.create(
                                instance=instance,
                                step=instance.step,
                                approver_man_number=request.user,
                                action_status=dra_action_status,
                                comment="下書き保存",
                            )
                        except Exception:
                            pass

                    # ワークフローインスタンス作成＆承認者登録（下書き時はスキップ）
                    if not is_draft and doc_type.workflow_template_id:
                        wf = doc_type.workflow_template_id
                        steps = steps_with_candidates(request.user, wf)
                        # POSTから承認者選択を取得
                        approver_errors = []
                        created_instance = None
                        from .models import T_WorkflowInstance, T_DocumentApprover, M_WorkflowStep, M_User, T_WorkflowAction
                        # 最初のステップを現在ステップに設定
                        first_step = None
                        if steps:
                            # steps は辞書。実体の M_WorkflowStep を取得
                            from .models import M_WorkflowStep
                            try:
                                first_step = M_WorkflowStep.objects.get(pk=steps[0]['step_id'])
                            except M_WorkflowStep.DoesNotExist:
                                first_step = None
                        # インスタンスの状態も文書の状態（SUB）と合わせる
                        wf_status = expense.status_cd
                        created_instance = T_WorkflowInstance.objects.create(
                            document_id=expense,
                            workflow_template=wf,
                            status=wf_status,
                            step=first_step,
                            step_order=(steps[0]['step_order'] if steps else None),
                        )
                        # 初回申請（SUB）を履歴に記録
                        try:
                            # expense.status_cd は SUB に設定済み
                            T_WorkflowAction.objects.create(
                                instance=created_instance,
                                step=first_step,
                                approver_man_number=request.user,
                                action_status=expense.status_cd,
                                comment="申請者による提出",
                            )
                        except Exception:
                            pass
                        for s in steps:
                            step_id = s['step_id']
                            scope = s['allowed_bumon_scope']
                            selected = None
                            field_name = f"approver_step_{step_id}"
                            # ここから先は承認者割当の検証・生成
                            if scope == 'keiri':
                                cand = s['candidates'][0] if s['candidates'] else None
                                if cand:
                                    selected = cand['man_number']
                                else:
                                    continue
                            else:
                                selected = request.POST.get(field_name) or None
                                if not selected:
                                    approver_errors.append(f"ステップ{ s['step_order'] }の承認者を選択してください。")
                                    continue

                            valid_man_numbers = {c['man_number'] for c in s['candidates']}
                            if selected and selected not in valid_man_numbers:
                                approver_errors.append(f"ステップ{ s['step_order'] }の承認者が不正です。")
                                continue

                            if selected:
                                # 生成
                                step_obj = M_WorkflowStep.objects.get(pk=step_id)
                                approver_user = M_User.objects.get(man_number=selected)
                                T_DocumentApprover.objects.create(
                                    document_id=expense,
                                    step_id=step_obj,
                                    man_number=approver_user,
                                    step_order=s['step_order'],
                                    status='pending'
                                )
                        if approver_errors:
                            raise Exception(" ".join(approver_errors))

                        # 提出後、最初の承認者に通知（登録済みの承認予定者へ）
                        try:
                            if created_instance and first_step:
                                from .models import T_DocumentApprover
                                next_approvers = T_DocumentApprover.objects.filter(
                                    document_id=expense,
                                    step_id=first_step,
                                    step_order=getattr(first_step, 'step_order', None),
                                )
                                subject, body = _build_approval_request_mail(expense)
                                if next_approvers.exists():
                                    for a in next_approvers:
                                        to_addr = getattr(getattr(a.man_number, 'email', None), 'strip', lambda: None)()
                                        send_notification(to_addr, subject, body)
                        except Exception:
                            pass

                # 二重送信防止トークンを処理済みに登録
                if submission_id:
                    processed.add(submission_id)
                    request.session['processed_submission_ids'] = list(processed)

                print("Redirecting to home")
                return redirect('expenses:home')
            except M_Status.DoesNotExist as e:
                print("Status error:", str(e))
                error_message = "申請ステータスの設定に失敗しました。"
            except Exception as e:
                print("Unexpected error:", str(e))
                error_message = f"予期せぬエラーが発生しました: {str(e)}"
        elif not currency_valid:
            error_message = "通貨の選択が不正です。"
    else:
        _aq = _get_account_queryset(resolved_doc_type)
        expense_formset = None
        accom_formset = None
        allow_formset = None
        tra_items = M_Item.objects.filter(data_kbn='TRA').order_by('key')
        if _is_travel_doc_type(resolved_doc_type):
            formset = TravelDetailFormSet(queryset=T_DocumentContent.objects.none(), prefix='travel')
            if len(formset.forms) > 1:
                formset.forms = formset.forms[:1]
            accom_formset = AccommodationFormSet(queryset=T_DocumentContent.objects.none(), prefix='accom')
            allow_formset = AllowanceFormSet(queryset=T_DocumentContent.objects.none(), prefix='allow', tra_items=tra_items)
        else:
            formset = ExpenseDetailFormSet(queryset=T_DocumentContent.objects.none(), account_queryset=_aq)
            # 空のフォームが1つだけ表示されるように調整
            if len(formset.forms) > 1:
                formset.forms = formset.forms[:1]
                formset.management_form.initial['TOTAL_FORMS'] = 1
        error_message = None
        # 二重送信防止トークンを生成
        submission_id = str(uuid.uuid4())
        # 後で検証するために pending に格納（用途があれば）
        pending = set(request.session.get('pending_submission_ids', []))
        pending.add(submission_id)
        request.session['pending_submission_ids'] = list(pending)
    
    # 組織一覧・部門一覧の取得
    groups = M_Group.objects.all().order_by('group_cd')
    pay_items = M_Item.objects.filter(data_kbn='pay').order_by('key')
    currencies = M_Item.objects.filter(data_kbn='CUR').order_by('key')
    
    # 承認候補 UI 用データ（GET/POST で同じ構造を出す）
    workflow_steps = []
    # テンプレート見出しなどで使用する現在の DocType を準備
    doc_type = None
    try:
        # 表示時の承認候補 UI: 引数の DocType を優先
        if document_type_id:
            doc_type = M_DocumentType.objects.filter(document_type_id=document_type_id).first()
        if not doc_type:
            doc_type = M_DocumentType.objects.filter(document_type_name="経費精算書").first()
        if doc_type and doc_type.workflow_template_id:
            workflow_steps = steps_with_candidates(request.user, doc_type.workflow_template_id)
    except Exception:
        workflow_steps = []

    # doc_type 確定後に bumon_scope を参照して部門リストを絞り込む
    bumons = _get_bumons_for_user(request.user, doc_type)

    # テンプレートでプリセレクトできるように、各ステップに selected を付与
    if workflow_steps:
        if request.method == "POST":
            for s in workflow_steps:
                key = f"approver_step_{s['step_id']}"
                s['selected'] = request.POST.get(key, '')
        else:
            for s in workflow_steps:
                s['selected'] = ''
        # others の場合、選択済みがあれば所属グループ候補もプリセット（新規では通常空）
        for s in workflow_steps:
            s.setdefault('selected_group_cd', '')

    _create_template = (
        "expenses/travel_expense_form.html"
        if _is_travel_doc_type(doc_type or resolved_doc_type)
        else "expenses/expense_form.html"
    )
    return render(request, _create_template, {
        "formset": formset,
        "expense_formset": expense_formset,
        "accom_formset": accom_formset,
        "allow_formset": allow_formset,
        "tra_items": tra_items if _is_travel_doc_type(doc_type or resolved_doc_type) else [],
        "is_edit_mode": False,
        "expense": None,
        "error_message": error_message,
        "groups": groups,
        "bumons": bumons,
        "pay_items": pay_items,
        "currencies": currencies,
        "submission_id": submission_id if request.method == "GET" else request.POST.get('submission_id'),
        "workflow_steps": workflow_steps,
        "dynamic_fields": dynamic_fields,
        # 見出し用: 現在の文書種別
        "current_doc_type": doc_type,
        "current_doc_type_name": getattr(doc_type, 'document_type_name', None),
        # サイドメニューからの初回表示時に DocType=1 のWFをダイアログ表示するための値
        "doc1_workflow_template_id": doc1_wf_id,
        "doc1_document_type_name": doc1_name,
        "show_doc1_alert": request.method == "GET",
        # コピー申請用（通常の新規申請では空文字）
        "copy_from_expense": None,
        "copy_from_bumon_cd": "",
        "copy_from_tsuka_cd": "",
        "copy_from_memo": "",
        "copy_from_ringi_no": "",
        "form_action": "",
        # カテゴリ別フィールド制御
        **_asset_form_context(doc_type or resolved_doc_type),
    })

@login_required
def expense_copy(request, pk):
    """既存申請のデータをコピーして新規申請フォームを表示する（GET only）"""
    source = get_object_or_404(T_Document, pk=pk)

    # コピー元明細を取得
    details = list(source.contents.all().order_by('document_detail_id'))
    n = max(len(details), 1)

    # フォームセットをコピー用に動的生成（extra=n）
    from django.forms import modelformset_factory
    from .forms import ExpenseDetailForm, BaseExpenseDetailFormSet
    CopyFormSet = modelformset_factory(
        T_DocumentContent,
        form=ExpenseDetailForm,
        formset=BaseExpenseDetailFormSet,
        extra=n,
        can_delete=False,
        validate_min=False,
        min_num=0,
        validate_max=True,
        max_num=10,
    )

    _aq = _get_account_queryset(source.document_type)

    # 各明細の初期値
    initial = []
    for d in details:
        initial.append({
            'date': d.date,
            'amount': d.amount,
            'purpose': d.purpose or '',
            'shiharaisaki': d.shiharaisaki or '',
            'account': d.account,
            'tekikaku_cd': d.tekikaku_cd or '',
            'corpo_card': d.corpo_card,
            'corpo_card_no': d.corpo_card_no or '',
        })

    formset = CopyFormSet(
        queryset=T_DocumentContent.objects.none(),
        account_queryset=_aq,
        initial=initial,
    )

    # フォームの POST 先 URL（document_type_id を引き継ぐ）
    from django.urls import reverse as url_reverse
    doc_type = source.document_type
    if doc_type:
        form_action = url_reverse('expenses:expense_create_by_type', kwargs={'document_type_id': doc_type.document_type_id})
    else:
        form_action = url_reverse('expenses:expense_create')

    # 承認候補（コピー元の承認者をプリセレクト）
    workflow_steps = []
    try:
        if doc_type and doc_type.workflow_template_id:
            workflow_steps = steps_with_candidates(request.user, doc_type.workflow_template_id)
    except Exception:
        workflow_steps = []
    if workflow_steps:
        from .models import T_DocumentApprover, M_BelongTo
        existing = T_DocumentApprover.objects.filter(document_id=source)
        selected_map = {}
        for a in existing:
            try:
                step_pk = getattr(a, 'step_id_id', None)
                if step_pk is None:
                    step_pk = getattr(getattr(a, 'step_id', None), 'step_id', None)
                selected_map[step_pk] = getattr(a.man_number, 'man_number', None)
            except Exception:
                pass
        for s in workflow_steps:
            s['selected'] = selected_map.get(s['step_id'], '') or ''
            s.setdefault('selected_group_cd', '')
        # others タイプは選択済みユーザーの所属グループもプリセット
        for s in workflow_steps:
            try:
                if s.get('allowed_bumon_scope') == 'others' and s.get('selected'):
                    grp = (
                        M_BelongTo.objects
                        .filter(man_number__man_number=s['selected'])
                        .values_list('group_cd__group_cd', flat=True)
                        .first()
                    )
                    if grp:
                        s['selected_group_cd'] = grp
            except Exception:
                pass

    groups = M_Group.objects.all().order_by('group_cd')
    bumons = _get_bumons_for_user(request.user, doc_type)
    pay_items = M_Item.objects.filter(data_kbn='pay').order_by('key')
    currencies = M_Item.objects.filter(data_kbn='CUR').order_by('key')

    # DocType=4: 動的フィールド定義をコピー元の値でプリセット
    dynamic_fields_for_copy = []
    try:
        if _has_dynamic_fields(doc_type):
            first_detail = source.contents.order_by('document_detail_id').first()
            existing_dyn = first_detail.content if (first_detail and isinstance(first_detail.content, dict)) else {}
            _dyn_dt_cp = _resolve_dynamic_fields_doc_type(doc_type)
            defs = M_DocumentField.objects.filter(document_type=_dyn_dt_cp).order_by('field_order', 'field_name')
            for d in defs:
                raw_type = (d.field_type or '').strip().lower()
                html_type = 'text'
                options = []
                if raw_type.startswith('select'):
                    html_type = 'select'
                    parts = raw_type.split(':', 1)
                    if len(parts) == 2 and parts[1]:
                        kbn = parts[1].strip()
                        options = list(
                            M_Item.objects.filter(data_kbn__iexact=kbn).order_by('key').values('key', 'content')
                        )
                elif raw_type in ('text', 'number', 'date'):
                    html_type = raw_type
                elif raw_type == 'num':
                    html_type = 'number'
                elif raw_type == 'label':
                    html_type = 'label'
                dynamic_fields_for_copy.append({
                    'name':          d.field_name,
                    'label':         (d.field_name_view or d.field_name),
                    'type':          html_type,
                    'options':       options,
                    'value':         existing_dyn.get(d.field_name, '') if html_type != 'label' else '',
                    'col_width':     d.col_width or 4,
                    'row_break':     d.row_break,
                    'required':      d.required,
                    'placeholder':   d.placeholder or '',
                    'field_help_text': d.field_help_text or '',
                    'calc_formula':  d.calc_formula or '',
                    'section_header': d.section_header or '',
                })
    except Exception:
        dynamic_fields_for_copy = []

    # DocType=5 (出張旅費精算) コピーの場合は専用フォームへ
    if _is_travel_doc_type(doc_type):
        from .forms import TravelDetailFormSet as TravelCopyFormSet, AccommodationFormSet, AllowanceFormSet
        all_details = list(source.details.all())
        route_details = [d for d in all_details if isinstance(d.content, dict) and 'departure' in d.content]
        n_routes = max(len(route_details), 1)
        from django.forms import modelformset_factory
        from .forms import TravelDetailForm
        TravelCopyFS = modelformset_factory(
            T_DocumentContent,
            form=TravelDetailForm,
            extra=n_routes,
            can_delete=False,
            validate_min=False,
            min_num=0,
            validate_max=True,
            max_num=30,
        )
        travel_initial = []
        for d in route_details:
            c = d.content if isinstance(d.content, dict) else {}
            travel_initial.append({
                'date':         d.date,
                'amount':       d.amount,
                'purpose':      d.purpose or '',
                'shiharaisaki': d.shiharaisaki or '',
                'departure':    c.get('departure', ''),
                'arrival':      c.get('arrival', ''),
                'transport':    c.get('transport', ''),
                'duration':     c.get('duration', ''),
                'tekikaku_flag': c.get('tekikaku_flag', '無'),
            })
        travel_formset = TravelCopyFS(
            queryset=T_DocumentContent.objects.none(),
            initial=travel_initial,
            prefix='travel',
        )
        tra_items = M_Item.objects.filter(data_kbn='TRA').order_by('key')
        accom_formset = AccommodationFormSet(queryset=T_DocumentContent.objects.none(), prefix='accom')
        allow_formset = AllowanceFormSet(queryset=T_DocumentContent.objects.none(), prefix='allow', tra_items=tra_items)
        return render(request, "expenses/travel_expense_form.html", {
            "formset": travel_formset,
            "accom_formset": accom_formset,
            "allow_formset": allow_formset,
            "tra_items": tra_items,
            "is_edit_mode": False,
            "expense": None,
            "groups": groups,
            "bumons": bumons,
            "pay_items": pay_items,
            "currencies": currencies,
            "workflow_steps": workflow_steps,
            "submission_id": str(uuid.uuid4()),
            "error_message": None,
            "copy_from_expense": source,
            "copy_from_bumon_cd": source.bumon_cd.bumon_cd if source.bumon_cd else "",
            "copy_from_tsuka_cd": source.tsuka_cd or "00",
            "copy_from_memo": source.memo or "",
            "copy_from_ringi_no": source.ringi_no or "",
            "form_action": form_action,
            "current_doc_type_name": getattr(doc_type, 'document_type_name', '出張旅費精算') + "（コピー）",
            **_asset_form_context(doc_type),
        })

    return render(request, "expenses/expense_form.html", {
        "formset": formset,
        "groups": groups,
        "bumons": bumons,
        "pay_items": pay_items,
        "currencies": currencies,
        "workflow_steps": workflow_steps,
        "dynamic_fields": dynamic_fields_for_copy,
        "submission_id": str(uuid.uuid4()),
        "error_message": None,
        "copy_from_expense": source,
        "copy_from_bumon_cd": source.bumon_cd.bumon_cd if source.bumon_cd else "",
        "copy_from_tsuka_cd": source.tsuka_cd or "00",
        "copy_from_memo": source.memo or "",
        "copy_from_ringi_no": source.ringi_no or "",
        "form_action": form_action,
        "current_doc_type_name": getattr(doc_type, 'document_type_name', '経費申請') + "（コピー）",
        "doc1_wf_id": None,
        # カテゴリ別フィールド制御
        **_asset_form_context(doc_type),
    })

@login_required
def approval_list(request):
    from .models import T_DocumentApprover
    is_role_allowed = request.user.role in ["accountant", "final_approver", "approver"]
    is_listed_as_approver = T_DocumentApprover.objects.filter(man_number=request.user).exists()
    if not (is_role_allowed or is_listed_as_approver):
        raise PermissionDenied()

    base_qs = T_Document.objects.filter(
        status_cd__status_cd__in=["INPRO", "APPROVED"]
    ).select_related('status_cd', 'document_type', 'man_number', 'bumon_cd').prefetch_related('contents')

    approver_docs = T_DocumentApprover.objects.filter(man_number=request.user).values_list('document_id', flat=True)
    approvals = base_qs.filter(
        Q(man_number__bumon_cd=request.user.bumon_cd) | Q(document_id__in=approver_docs)
    ).order_by('-created_at')

    # フィルター
    status_filter = request.GET.get('status', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    keyword = request.GET.get('keyword', '')

    if status_filter:
        approvals = approvals.filter(status_cd__status_name=status_filter)
    approvals = _apply_created_at_date_range(approvals, date_from, date_to)
    if keyword:
        approvals = approvals.filter(
            Q(title__icontains=keyword) |
            Q(man_number__user_name__icontains=keyword) |
            Q(contents__purpose__icontains=keyword)
        ).distinct()

    # ページネーション
    paginator = Paginator(approvals, 20)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    from django.db.models import Min
    statuses = (
        M_Status.objects
        .filter(status_cd__in=['INPRO', 'APPROVED'])
        .values('status_name')
        .annotate(min_order=Min('order_by'))
        .order_by('min_order', 'status_name')
    )

    progress_by_doc = _get_step_progress_map([d.document_id for d in page_obj])

    return render(request, "expenses/approval_list.html", {
        "approvals": page_obj,
        "page_obj": page_obj,
        "statuses": statuses,
        "status_filter": status_filter,
        "date_from": date_from,
        "date_to": date_to,
        "keyword": keyword,
        "progress_by_doc": progress_by_doc,
    })


@login_required
def approval_csv(request):
    """承認一覧のCSVエクスポート"""
    from .models import T_DocumentApprover
    is_role_allowed = request.user.role in ["accountant", "final_approver", "approver"]
    is_listed_as_approver = T_DocumentApprover.objects.filter(man_number=request.user).exists()
    if not (is_role_allowed or is_listed_as_approver):
        raise PermissionDenied()

    base_qs = T_Document.objects.filter(
        status_cd__status_cd__in=["INPRO", "APPROVED"]
    ).select_related('status_cd', 'document_type', 'man_number', 'bumon_cd').prefetch_related('contents')

    approver_docs = T_DocumentApprover.objects.filter(man_number=request.user).values_list('document_id', flat=True)
    approvals = base_qs.filter(
        Q(man_number__bumon_cd=request.user.bumon_cd) | Q(document_id__in=approver_docs)
    ).order_by('-created_at')

    status_filter = request.GET.get('status', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    keyword = request.GET.get('keyword', '')

    if status_filter:
        approvals = approvals.filter(status_cd__status_cd=status_filter)
    approvals = _apply_created_at_date_range(approvals, date_from, date_to)
    if keyword:
        approvals = approvals.filter(
            Q(title__icontains=keyword) |
            Q(man_number__user_name__icontains=keyword) |
            Q(contents__purpose__icontains=keyword)
        ).distinct()

    response = HttpResponse(content_type='text/csv; charset=utf-8-sig')
    response['Content-Disposition'] = 'attachment; filename="approvals.csv"'
    writer = csv.writer(response)
    writer.writerow(['申請ID', '申請種別', '申請者', '部門', '申請日時', '目的', '合計金額', '通貨', 'ステータス'])
    for exp in approvals:
        first_content = exp.contents.first()
        writer.writerow([
            exp.document_id,
            exp.document_type.document_type_name if exp.document_type else '',
            exp.man_number.user_name if exp.man_number else '',
            exp.bumon_cd.bumon_name if exp.bumon_cd else '',
            timezone.localtime(exp.created_at).strftime('%Y/%m/%d %H:%M'),
            first_content.purpose if first_content else '',
            exp.total_amount,
            exp.tsuka_cd or '',
            exp.status_cd.status_name if exp.status_cd else '',
        ])
    return response

# 旧: 組織から承認者候補を取得する補助APIはワークフロー候補抽出に置き換えたため削除

@login_required
def approval_detail(request, pk):
    expense = get_object_or_404(T_Document, pk=pk)
    if request.user.role not in ["accountant", "final_approver", "approver"]:
        raise PermissionDenied()
    if request.user.role == "approver" and expense.man_number.bumon_cd != request.user.bumon_cd:
        raise PermissionDenied()
    if request.method == "POST":
        form = ApprovalForm(request.POST)
        if form.is_valid():
            status_code = form.cleaned_data["status"]
            # ステータス未登録時でも落ちないように補完（統一コード）
            try:
                status = M_Status.objects.get(status_cd=status_code)
            except M_Status.DoesNotExist:
                default_names = {
                    "APPROVED": "回覧中",
                    "REJECTED": "却下",
                    "RETURNED": "差し戻し中",
                }
                default_actions = {
                    "APPROVED": "承認",
                    "REJECTED": "却下",
                    "RETURNED": "差し戻し",
                }
                status = M_Status.objects.create(
                    status_cd=status_code,
                    status_name=default_names.get(status_code, status_code),
                    action_name=default_actions.get(status_code, status_code),
                )
            comment = form.cleaned_data["comment"]
            # 文書ステータスは各アクション分岐で適切に更新する
            # （中間 APPROVED は INPRO のまま、最終承認/却下/差戻しは各 elif で確定）
            try:
                from .models import T_WorkflowInstance, T_WorkflowAction, M_WorkflowStep, T_DocumentApprover
                instance = T_WorkflowInstance.objects.filter(document_id=expense).order_by('-started_at').first()
                if instance:
                    # 1) アクション履歴
                    T_WorkflowAction.objects.create(
                        instance=instance,
                        step=instance.step,
                        approver_man_number=request.user,
                        action_status=status,
                        comment=comment,
                    )

                    # 2) アクションごとの遷移・完了処理・承認者記録
                    if status.status_cd == 'APPROVED':
                        now = timezone.now()
                        # 承認者予定のステータス更新（同一ステップ）
                        try:
                            # 現ステップ情報
                            current_order = instance.step_order or (instance.step.step_order if instance.step else None)
                            approver_qs = T_DocumentApprover.objects.filter(
                                document_id=expense,
                                step_id=instance.step,
                                step_order=current_order,
                            )
                            target = approver_qs.filter(man_number=request.user).first() or approver_qs.first()
                            if target:
                                target.status = 'APPROVED'
                                target.approved_at = now
                                if getattr(target.man_number, 'man_number', None) != getattr(request.user, 'man_number', None):
                                    who = f"{getattr(request.user, 'user_name', '')}({getattr(request.user, 'man_number', '')})"
                                    target.remarks = (target.remarks + "\n" if target.remarks else "") + f"実行者: {who}"
                                target.save()
                        except Exception:
                            pass

                        # 次ステップ遷移 or 完了
                        try:
                            current_order = instance.step_order or (instance.step.step_order if instance.step else None)
                            next_step = None
                            if current_order is not None:
                                next_step = (
                                    M_WorkflowStep.objects
                                    .filter(workflow_template=instance.workflow_template, step_order__gt=current_order)
                                    .order_by('step_order')
                                    .first()
                                )
                            if next_step:
                                instance.step = next_step
                                instance.step_order = next_step.step_order
                                instance.save(update_fields=['step', 'step_order'])
                                # 中間承認: 文書ステータスは「申請中(INPRO)」のまま継続
                                inpro = M_Status.objects.get_or_create(
                                    status_cd='INPRO', defaults={'status_name': '申請中', 'action_name': '提出'}
                                )[0]
                                expense.status_cd = inpro
                                expense.updated_at = now
                                expense.save(update_fields=['status_cd', 'updated_at'])
                                # 次の承認者に通知
                                try:
                                    from .models import T_DocumentApprover
                                    # 次ステップに pending の承認予定者が存在すれば通知（なければ候補抽出に基づく運用に応じて拡張可）
                                    next_approvers = T_DocumentApprover.objects.filter(
                                        document_id=expense,
                                        step_id=next_step,
                                        step_order=next_step.step_order,
                                    )
                                    # 件名/本文
                                    subject, body = _build_approval_request_mail(
                                        expense, f"【次の承認ステップ ({next_step.step_order})】"
                                    )
                                    # 強制送信先がある場合はそちらへ（utils側で切替）
                                    if next_approvers.exists():
                                        for a in next_approvers:
                                            to_addr = getattr(getattr(a.man_number, 'email', None), 'strip', lambda: None)()
                                            send_notification(to_addr, subject, body)
                                    else:
                                        # 承認予定が未登録でも最低1通は送る（運用に合わせて調整可）
                                        to_addr = getattr(getattr(expense.man_number, 'email', None), 'strip', lambda: None)()
                                        send_notification(to_addr, subject, body)
                                except Exception:
                                    pass
                            else:
                                # 最終承認: インスタンス/文書を FNS に
                                fns = M_Status.objects.get_or_create(status_cd='FNS', defaults={'status_name': '承認済み', 'action_name': '承認'})[0]
                                instance.status = fns
                                instance.completed_at = now
                                instance.save(update_fields=['status', 'completed_at'])
                                expense.status_cd = fns
                                expense.updated_at = now
                                expense.save(update_fields=['status_cd', 'updated_at'])
                        except Exception:
                            pass
                    elif status.status_cd == 'REJECTED':
                        # 却下: ワークフローを完了（REJ）し、文書の状態も REJ に
                        now = timezone.now()
                        try:
                            # 承認予定者レコード更新
                            from .models import T_DocumentApprover
                            current_order = instance.step_order or (instance.step.step_order if instance.step else None)
                            approver_qs = T_DocumentApprover.objects.filter(
                                document_id=expense,
                                step_id=instance.step,
                                step_order=current_order,
                            )
                            target = approver_qs.filter(man_number=request.user).first() or approver_qs.first()
                            if target:
                                target.status = 'REJECTED'
                                target.approved_at = now
                                if getattr(target.man_number, 'man_number', None) != getattr(request.user, 'man_number', None):
                                    who = f"{getattr(request.user, 'user_name', '')}({getattr(request.user, 'man_number', '')})"
                                    target.remarks = (target.remarks + "\n" if target.remarks else "") + f"実行者: {who}"
                                target.save()
                        except Exception:
                            pass

                        try:
                            instance.status = status  # REJECTED
                            instance.completed_at = now
                            instance.save(update_fields=['status', 'completed_at'])
                            expense.status_cd = status  # REJECTED
                            expense.updated_at = now
                            expense.save(update_fields=['status_cd', 'updated_at'])
                        except Exception:
                            pass
                    elif status.status_cd == 'RETURNED':
                        # 差戻し: 一つ前のステップに戻し、状態を RET に
                        now = timezone.now()
                        try:
                            # 承認予定者レコード更新（操作の記録として RET を付ける）
                            from .models import T_DocumentApprover, M_WorkflowStep
                            current_order = instance.step_order or (instance.step.step_order if instance.step else None)
                            approver_qs = T_DocumentApprover.objects.filter(
                                document_id=expense,
                                step_id=instance.step,
                                step_order=current_order,
                            )
                            target = approver_qs.filter(man_number=request.user).first() or approver_qs.first()
                            if target:
                                target.status = 'RETURNED'
                                target.approved_at = now
                                if getattr(target.man_number, 'man_number', None) != getattr(request.user, 'man_number', None):
                                    who = f"{getattr(request.user, 'user_name', '')}({getattr(request.user, 'man_number', '')})"
                                    target.remarks = (target.remarks + "\n" if target.remarks else "") + f"実行者: {who}"
                                target.save()

                            # 前のステップへ戻す
                            prev_step = None
                            if current_order is not None:
                                prev_step = (
                                    M_WorkflowStep.objects
                                    .filter(workflow_template=instance.workflow_template, step_order__lt=current_order)
                                    .order_by('-step_order')
                                    .first()
                                )
                            if prev_step:
                                instance.step = prev_step
                                instance.step_order = prev_step.step_order
                            instance.status = status  # RETURNED（差し戻し中）
                            instance.save(update_fields=['step', 'step_order', 'status'])
                            expense.status_cd = status
                            expense.updated_at = now
                            expense.save(update_fields=['status_cd', 'updated_at'])
                        except Exception:
                            pass
            except Exception:
                pass
            # 申請結果メールは FNS/REJECTED/RETURNED のときに申請者へ送信（APPROVEDの中間状態では送らない）
            try:
                final_code = getattr(getattr(expense, 'status_cd', None), 'status_cd', None)
                if final_code in {'FNS', 'REJECTED', 'RETURNED'}:
                    final_name = getattr(expense.status_cd, 'status_name', final_code)
                    send_notification(
                        expense.man_number.email,
                        "[経費精算] 申請結果",
                        f"申請ID:{expense.document_id} の結果: {final_name}\nコメント: {comment or 'なし'}"
                    )
            except Exception:
                pass
            return redirect("expenses:approval_list")
    else:
        form = ApprovalForm()

    # ワークフロー履歴を取得
    workflow_actions = []
    try:
        from .models import T_WorkflowAction
        workflow_actions = (
            T_WorkflowAction.objects
            .filter(instance__document_id=expense)
            .select_related('action_status', 'approver_man_number', 'step', 'instance')
            .order_by('actioned_at')
        )
    except Exception:
        workflow_actions = []

    # 承認予定者を取得（未承認 = pending/draft + 未処理の keiri ステップ）
    try:
        pending_approvers = get_pending_approvers(expense)
    except Exception:
        pending_approvers = []

    dynamic_fields_display = _build_dynamic_fields_display(expense)

    progress = _get_step_progress_map([expense.document_id]).get(expense.document_id)

    is_travel = _is_travel_doc_type(expense.document_type)
    travel_route_details = []
    travel_accom_details = []
    travel_allow_details = []
    if is_travel:
        _all_details = list(expense.details.prefetch_related('attachments'))
        travel_route_details = [d for d in _all_details if isinstance(d.content, dict) and 'departure' in d.content]
        travel_accom_details = [d for d in _all_details if isinstance(d.content, dict) and d.content.get('row_type') == 'accommodation']
        travel_allow_details = [d for d in _all_details if isinstance(d.content, dict) and d.content.get('row_type') == 'allowance']

    return render(request, "expenses/approval_detail.html", {
        "expense": expense,
        "form": form,
        "workflow_actions": workflow_actions,
        "pending_approvers": pending_approvers,
        "dynamic_fields_display": dynamic_fields_display,
        "progress": progress,
        "is_travel": is_travel,
        "travel_route_details": travel_route_details,
        "travel_accom_details": travel_accom_details,
        "travel_allow_details": travel_allow_details,
    })


@login_required
def approver_candidates(request):
    """allowed_bumon_scope == 'others' 用: 指定部門の承認候補を返す。
    GET パラメータ: step_id, bumon_cd
    役職条件(approver_post)と申請者除外を適用。
    """
    step_id = request.GET.get('step_id')
    group_cd = request.GET.get('group_cd')
    bumon_cd = request.GET.get('bumon_cd')
    if not step_id or (not group_cd and not bumon_cd):
        return HttpResponseBadRequest('missing parameters')
    try:
        from .models import M_WorkflowStep, V_Group
        step = M_WorkflowStep.objects.select_related('approver_post').get(pk=int(step_id))
    except Exception:
        return HttpResponseBadRequest('invalid step_id')
    try:
        qs = M_User.objects.select_related('post_cd', 'bumon_cd')
        if group_cd:
            # 選択グループに加え、v_groupの relation_group_cd = group_cd の group_cd も対象に含める
            related_group_qs = V_Group.objects.filter(relation_group_cd=group_cd).values_list('group_cd', flat=True)
            qs = qs.filter(belongs__group_cd__group_cd__in=list(related_group_qs) + [group_cd])
        elif bumon_cd:
            qs = qs.filter(bumon_cd__bumon_cd=bumon_cd)
        if step.approver_post:
            threshold = step.approver_post.post_order
            qs = qs.filter(post_cd__post_order__lte=threshold)
        # 自分自身は除外
        qs = qs.exclude(pk=request.user.pk)
        qs = qs.order_by('post_cd__post_order', 'user_name').distinct()
        members = [{
            'man_number': u.man_number,
            'user_name': u.user_name,
            'post_name': (u.post_cd.post_name if u.post_cd else ''),
            'bumon_cd': (u.bumon_cd.bumon_cd if u.bumon_cd else ''),
            'bumon_name': (u.bumon_cd.bumon_name if u.bumon_cd else ''),
        } for u in qs]
        return JsonResponse({'members': members})
    except Exception:
        return JsonResponse({'members': []})


@login_required
def generate_mobile_upload_qr(request):
    """モバイルアップロード用QRコードを生成するAPI（JSON）。
    GET ?upload_id=xxx の場合は既存IDでQRを再生成。
    """

    if not request.user.is_authenticated:
        return JsonResponse({'error': 'セッションが切れました。再ログインしてください。'}, status=401)
    upload_id = request.GET.get('upload_id', '').strip()
    if not upload_id:
        upload_id = uuid.uuid4().hex[:12]

    base_url = getattr(settings, 'IMAGE_UP_APP_BASE_URL', '').strip().rstrip('/')
    if not base_url:
        return JsonResponse(
            {'error': 'IMAGE_UP_APP_BASE_URLが未設定です。管理者に連絡してください。'},
            status=500,
        )

    upload_url = f"{base_url}/?id={upload_id}"

    try:
        qr = qrcode.QRCode(box_size=8, border=2)
        qr.add_data(upload_url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        qr_b64 = base64.b64encode(buf.getvalue()).decode('utf-8')
    except Exception as e:
        return JsonResponse({'error': f'QRコード生成に失敗しました: {e}'}, status=500)

    return JsonResponse({
        'upload_id': upload_id,
        'upload_url': upload_url,
        'qr_image': f'data:image/png;base64,{qr_b64}',
    })


def check_mobile_uploads(request):
    """モバイルアップロード済みファイルを確認するAPI（JSON）。
    GET ?upload_id=xxx
    """
    import logging, os, traceback as tb
    from .cloud_receipts import check_uploads_by_id, _GCS_ADC_PATH, _gcs_bucket, _gcs_folder
    logger = logging.getLogger(__name__)

    if not request.user.is_authenticated:
        return JsonResponse({'error': 'セッションが切れました。再ログインしてください。'}, status=401)

    upload_id = request.GET.get('upload_id', '').strip()
    if not upload_id:
        return JsonResponse({'error': 'upload_idが必要です。'}, status=400)

    # デバッグ用診断情報
    adc_path = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS', _GCS_ADC_PATH)
    debug_info = {
        'upload_id': upload_id,
        'adc_path': adc_path,
        'adc_exists': os.path.exists(adc_path),
        'gcs_bucket': _gcs_bucket(),
        'gcs_prefix': f"{_gcs_folder()}/{upload_id}_",
    }
    logger.info('[check_mobile_uploads] debug=%s', debug_info)

    include_thumbnails = request.GET.get('thumbnails', '0') == '1'

    try:
        items = check_uploads_by_id(upload_id)
        debug_info['status'] = 'ok'

        # サムネイル生成（thumbnails=1 かつ画像ファイルがある場合のみ）
        thumbnails = {}
        if include_thumbnails and items:
            try:
                import base64 as _b64
                import io as _io
                from PIL import Image as _Image
                from .cloud_receipts import _get_gcs_client, _gcs_bucket
                client = _get_gcs_client()
                bkt = client.bucket(_gcs_bucket())
                for item in items:
                    ct = item.get('content_type', '')
                    if not ct.startswith('image/'):
                        continue
                    try:
                        blob = bkt.blob(item['name'])
                        data = blob.download_as_bytes(timeout=15)
                        img = _Image.open(_io.BytesIO(data))
                        img.thumbnail((120, 120))
                        buf = _io.BytesIO()
                        img.convert('RGB').save(buf, format='JPEG', quality=70)
                        thumbnails[item['filename']] = 'data:image/jpeg;base64,' + _b64.b64encode(buf.getvalue()).decode()
                    except Exception:
                        pass
            except Exception:
                pass

        return JsonResponse({
            'upload_id': upload_id,
            'count': len(items),
            'items': items,
            'thumbnails': thumbnails,
            'debug': debug_info,
        })
    except Exception as e:
        debug_info['status'] = 'error'
        debug_info['traceback'] = tb.format_exc()
        logger.error('[check_mobile_uploads] error: %s', tb.format_exc())
        return JsonResponse({'error': str(e), 'debug': debug_info}, status=500)


# ============================================================
#  管理者画面 (設定メニュー)
# ============================================================

@login_required
def asset_home(request):
    """固定資産カテゴリのトップページ"""
    from .models import T_DocumentApprover
    in_progress = T_Document.objects.filter(
        man_number=request.user,
        document_type__menu_group__category='assets',
    ).exclude(
        status_cd__status_cd__in=['DRAFT', 'CANCEL', 'FNS', 'REJECTED']
    ).order_by('-created_at')[:5]

    drafts = T_Document.objects.filter(
        man_number=request.user,
        document_type__menu_group__category='assets',
        status_cd__status_cd='DRAFT',
    ).order_by('-created_at')[:5]

    home_doc_ids = [d.document_id for d in in_progress]
    progress_by_doc = _get_step_progress_map(home_doc_ids)

    asset_doc_types = M_DocumentType.objects.filter(menu_group__category='assets').order_by('document_type_id')

    return render(request, "expenses/asset_home.html", {
        'in_progress_expenses': in_progress,
        'draft_expenses': drafts,
        'progress_by_doc': progress_by_doc,
        'asset_doc_types': asset_doc_types,
    })


@login_required
def asset_list(request):
    """固定資産カテゴリの申請一覧"""
    qs = T_Document.objects.filter(
        man_number=request.user,
        document_type__menu_group__category='assets',
    ).select_related(
        'status_cd', 'document_type', 'bumon_cd'
    ).prefetch_related('contents').order_by("-created_at")

    status_filter = request.GET.get('status', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    keyword = request.GET.get('keyword', '')

    if status_filter:
        qs = qs.filter(status_cd__status_name=status_filter)
    qs = _apply_created_at_date_range(qs, date_from, date_to)
    if keyword:
        qs = qs.filter(
            Q(title__icontains=keyword) |
            Q(contents__purpose__icontains=keyword) |
            Q(memo__icontains=keyword)
        ).distinct()

    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get('page', 1))

    from django.db.models import Min
    statuses = (
        M_Status.objects
        .values('status_name')
        .annotate(min_order=Min('order_by'))
        .order_by('min_order', 'status_name')
    )
    progress_by_doc = _get_step_progress_map([d.document_id for d in page_obj])

    return render(request, "expenses/asset_list.html", {
        "expenses": page_obj,
        "page_obj": page_obj,
        "statuses": statuses,
        "status_filter": status_filter,
        "date_from": date_from,
        "date_to": date_to,
        "keyword": keyword,
        "progress_by_doc": progress_by_doc,
    })


@login_required
def settings_home(request):
    return redirect('expenses:settings_export')


@login_required
def settings_export(request):
    """管理: データ出力（全申請一覧＋CSVダウンロード）"""
    from django.db.models import Min
    doc_types = M_DocumentType.objects.all().order_by('document_type_id')
    # status_name 単位で重複除去（expense_list と同ロジック）
    statuses = (
        M_Status.objects
        .values('status_name')
        .annotate(min_order=Min('order_by'))
        .order_by('min_order', 'status_name')
    )
    bumons = M_Bumon.objects.all().order_by('bumon_cd')

    qs = T_Document.objects.select_related(
        'status_cd', 'document_type', 'man_number', 'bumon_cd'
    ).prefetch_related('contents').order_by('-created_at')

    date_from     = request.GET.get('date_from', '')
    date_to       = request.GET.get('date_to', '')
    doc_type_filter = request.GET.get('doc_type', '')
    status_filter = request.GET.get('status', '')
    bumon_filter  = request.GET.get('bumon', '')
    keyword       = request.GET.get('keyword', '')

    if doc_type_filter:
        qs = qs.filter(document_type__document_type_id=doc_type_filter)
    if status_filter:
        # ドロップダウンの選択値は status_name（expense_list と同ロジック）
        qs = qs.filter(status_cd__status_name=status_filter)
    if bumon_filter:
        qs = qs.filter(bumon_cd__bumon_cd=bumon_filter)
    qs = _apply_created_at_date_range(qs, date_from, date_to)
    if keyword:
        qs = qs.filter(
            Q(title__icontains=keyword) |
            Q(man_number__user_name__icontains=keyword) |
            Q(contents__purpose__icontains=keyword) |
            Q(memo__icontains=keyword)
        ).distinct()

    if 'csv' in request.GET:
        response = HttpResponse(content_type='text/csv; charset=utf-8-sig')
        response['Content-Disposition'] = 'attachment; filename="admin_export.csv"'
        writer = csv.writer(response)
        writer.writerow([
            '申請ID', '申請種別コード', '申請種別',
            '申請者', '社員番号',
            '部門コード', '部門',
            '申請日時', '合計金額', '通貨',
            'ステータスコード', 'ステータス', '備考',
            '明細ID', '明細日付',
            '勘定科目コード', '勘定科目',
            '支払先', '目的', '明細金額',
            '登録番号', 'コーポレートカード', 'カード下4桁',
        ])
        for exp in qs:
            doc_fields = [
                exp.document_id,
                exp.document_type.document_type_id if exp.document_type else '',
                exp.document_type.document_type_name if exp.document_type else '',
                exp.man_number.user_name if exp.man_number else '',
                exp.man_number.man_number if exp.man_number else '',
                exp.bumon_cd.bumon_cd if exp.bumon_cd else '',
                exp.bumon_cd.bumon_name if exp.bumon_cd else '',
                timezone.localtime(exp.created_at).strftime('%Y/%m/%d %H:%M'),
                exp.total_amount,
                exp.tsuka_cd or '',
                exp.status_cd.status_cd if exp.status_cd else '',
                exp.status_cd.status_name if exp.status_cd else '',
                exp.memo or '',
            ]
            contents = list(exp.contents.select_related('account').order_by('document_detail_id'))
            if contents:
                for c in contents:
                    corpo = {None: '', 0: '', 1: '使用'}.get(c.corpo_card, '')
                    # 登録番号: 先頭が't'なら大文字化、'T'以外なら付与
                    tekikaku = str(c.tekikaku_cd or '').strip()
                    if tekikaku:
                        if tekikaku.startswith('t'):
                            tekikaku = 'T' + tekikaku[1:]
                        elif not tekikaku.startswith('T'):
                            tekikaku = 'T' + tekikaku
                    writer.writerow(doc_fields + [
                        c.document_detail_id,
                        c.date.strftime('%Y/%m/%d') if c.date else '',
                        c.account.account_cd if c.account else '',
                        c.account.account_name if c.account else '',
                        c.shiharaisaki or '',
                        c.purpose or '',
                        c.amount if c.amount is not None else '',
                        tekikaku,
                        corpo,
                        c.corpo_card_no or '',
                    ])
            else:
                writer.writerow(doc_fields + ['', '', '', '', '', '', '', '', '', ''])
        return response

    paginator = Paginator(qs, 30)
    page_obj = paginator.get_page(request.GET.get('page', 1))

    return render(request, 'expenses/settings_export.html', {
        'page_obj': page_obj,
        'doc_types': doc_types,
        'statuses': statuses,
        'bumons': bumons,
        'date_from': date_from,
        'date_to': date_to,
        'doc_type_filter': doc_type_filter,
        'status_filter': status_filter,
        'bumon_filter': bumon_filter,
        'keyword': keyword,
        'total_count': qs.count(),
    })


def _build_approval_flow(doc_ids):
    """doc_id → 承認フローリスト を返す。keiri ステップも補完する。
    各要素: {'name': str, 'status': 'APPROVED'|'REJECTED'|'pending', 'step_order': int, 'is_keiri': bool}
    """
    from .models import M_WorkflowStep
    if not doc_ids:
        return {}

    # ① T_DocumentApprover から登録済み承認者を収集
    approvers_by_doc = {}
    covered_steps = {}  # doc_id -> set of step_id
    for ap in T_DocumentApprover.objects.filter(
        document_id__in=doc_ids
    ).select_related('man_number').order_by('document_id', 'step_order', 'id'):
        doc_id = ap.document_id_id
        if doc_id not in approvers_by_doc:
            approvers_by_doc[doc_id] = []
            covered_steps[doc_id] = set()
        approvers_by_doc[doc_id].append({
            'name': ap.man_number.user_name if ap.man_number else '-',
            'status': ap.status or 'pending',
            'step_order': ap.step_order,
            'approved_at': ap.approved_at,
            'is_keiri': False,
        })
        if ap.step_id_id:
            covered_steps[doc_id].add(ap.step_id_id)

    # ② ワークフローインスタンスからテンプレートを取得
    inst_by_doc = {}
    for inst in T_WorkflowInstance.objects.filter(
        document_id__in=doc_ids
    ).select_related('workflow_template').order_by('document_id', '-started_at'):
        if inst.document_id_id not in inst_by_doc:
            inst_by_doc[inst.document_id_id] = inst

    # ③ 各テンプレートの keiri ステップを取得
    template_ids = {inst.workflow_template_id for inst in inst_by_doc.values() if inst.workflow_template_id}
    keiri_by_template = {}
    for step in M_WorkflowStep.objects.filter(
        workflow_template__in=template_ids,
        allowed_bumon_scope='keiri'
    ).order_by('step_order'):
        tid = step.workflow_template_id
        keiri_by_template.setdefault(tid, []).append(step)

    # ④ 承認済み keiri ステップを特定
    done_keiri = {}  # doc_id -> set of step_id
    for act in T_WorkflowAction.objects.filter(
        instance__document_id__in=doc_ids,
        action_status_id='APPROVED'
    ).values('instance__document_id_id', 'step_id'):
        doc_id = act['instance__document_id_id']
        done_keiri.setdefault(doc_id, set()).add(act['step_id'])

    # ⑤ keiri ステップを補完
    for doc_id in doc_ids:
        inst = inst_by_doc.get(doc_id)
        if not inst:
            continue
        keiri_steps = keiri_by_template.get(inst.workflow_template_id, [])
        covered = covered_steps.get(doc_id, set())
        done = done_keiri.get(doc_id, set())
        for step in keiri_steps:
            if step.step_id in covered:
                continue
            approvers_by_doc.setdefault(doc_id, []).append({
                'name': '[経理]',
                'status': 'APPROVED' if step.step_id in done else 'pending',
                'step_order': step.step_order,
                'approved_at': None,
                'is_keiri': True,
            })

    # ⑥ step_order 順に整列
    for doc_id in approvers_by_doc:
        approvers_by_doc[doc_id].sort(key=lambda x: (x['step_order'], x['name']))

    return approvers_by_doc


def _get_last_action_dates(doc_ids):
    """doc_id → 最終処理日時 (datetime|None) を返す。"""
    from django.db.models import Max
    result = {}
    rows = (T_WorkflowAction.objects
            .filter(instance__document_id__in=doc_ids)
            .values('instance__document_id_id')
            .annotate(last_at=Max('actioned_at')))
    for row in rows:
        result[row['instance__document_id_id']] = row['last_at']
    return result


def _get_step_progress_map(doc_ids):
    """doc_id → {'current': N, 'total': M} を返す。承認進行表示用。
    current は「承認済み件数」を表す（step_order は待機中ステップなので -1 する）。
    確定不能（インスタンス無し・テンプレート無し・総ステップ0）はキー不在。
    """
    if not doc_ids:
        return {}
    from django.db.models import Count
    # 各文書の最新ワークフローインスタンス
    inst_by_doc = {}
    for inst in (T_WorkflowInstance.objects
                 .filter(document_id__in=doc_ids)
                 .order_by('document_id', '-started_at')):
        if inst.document_id_id not in inst_by_doc:
            inst_by_doc[inst.document_id_id] = inst
    # テンプレート毎の総ステップ数
    template_ids = {inst.workflow_template_id for inst in inst_by_doc.values()
                    if inst.workflow_template_id}
    total_by_template = {}
    if template_ids:
        for row in (M_WorkflowStep.objects
                    .filter(workflow_template__in=template_ids)
                    .values('workflow_template_id')
                    .annotate(c=Count('step_id'))):
            total_by_template[row['workflow_template_id']] = row['c']
    result = {}
    for doc_id, inst in inst_by_doc.items():
        total = total_by_template.get(inst.workflow_template_id, 0)
        step_order = inst.step_order or 0
        if total > 0 and step_order > 0:
            # step_order は「現在待機中のステップ番号」なので、承認済み = step_order - 1
            # データ異常 (step_order > total) があっても total を上限にcap
            approved = max(0, min(step_order - 1, total))
            result[doc_id] = {'current': approved, 'total': total}
    return result


def _build_filter_qs(request, base_qs):
    """共通フィルターを base_qs に適用して (qs, params_dict) を返す。"""
    params = {
        'date_from':      request.GET.get('date_from', ''),
        'date_to':        request.GET.get('date_to', ''),
        'doc_type_filter': request.GET.get('doc_type', ''),
        'status_filter':  request.GET.get('status', ''),
        'bumon_filter':   request.GET.get('bumon', ''),
        'keyword':        request.GET.get('keyword', ''),
    }
    qs = base_qs
    if params['doc_type_filter']:
        qs = qs.filter(document_type__document_type_id=params['doc_type_filter'])
    if params['status_filter']:
        # status_name 単位で絞り込み（同名ステータスが複数あっても一括対応）
        qs = qs.filter(status_cd__status_name=params['status_filter'])
    if params['bumon_filter']:
        qs = qs.filter(bumon_cd__bumon_cd=params['bumon_filter'])
    qs = _apply_created_at_date_range(qs, params['date_from'], params['date_to'])
    if params['keyword']:
        qs = qs.filter(
            Q(title__icontains=params['keyword']) |
            Q(man_number__user_name__icontains=params['keyword']) |
            Q(contents__purpose__icontains=params['keyword'])
        ).distinct()
    return qs, params


@login_required
def settings_approval_admin(request):
    """管理: 承認管理一覧（承認フロー表示付き）"""
    from django.db.models import Min
    doc_types = M_DocumentType.objects.all().order_by('document_type_id')
    statuses = (
        M_Status.objects
        .values('status_name')
        .annotate(min_order=Min('order_by'))
        .order_by('min_order', 'status_name')
    )
    bumons = M_Bumon.objects.all().order_by('bumon_cd')

    base_qs = T_Document.objects.select_related(
        'status_cd', 'document_type', 'man_number', 'bumon_cd'
    ).prefetch_related('contents').order_by('-created_at')

    qs, params = _build_filter_qs(request, base_qs)
    # DRAFT はデフォルトで非表示（明示的に status=DRAFT を選んだ場合のみ表示）
    if not params['status_filter']:
        qs = qs.exclude(status_cd__status_cd='DRAFT')
    total_count = qs.count()

    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get('page', 1))

    doc_ids = [doc.document_id for doc in page_obj]
    approvers_by_doc = _build_approval_flow(doc_ids)
    last_action_by_doc = _get_last_action_dates(doc_ids)
    progress_by_doc = _get_step_progress_map(doc_ids)

    return render(request, 'expenses/settings_approval_admin.html', {
        'page_obj': page_obj,
        'doc_types': doc_types,
        'statuses': statuses,
        'bumons': bumons,
        'approvers_by_doc': approvers_by_doc,
        'last_action_by_doc': last_action_by_doc,
        'progress_by_doc': progress_by_doc,
        'total_count': total_count,
        **params,
    })


@login_required
def settings_approval_detail(request, pk):
    """管理: 承認詳細（approval_detail 相当 + 強制操作ボタン）"""
    expense = get_object_or_404(
        T_Document.objects.select_related('status_cd', 'document_type', 'man_number', 'bumon_cd'),
        pk=pk
    )

    # ワークフロー履歴
    workflow_actions = (
        T_WorkflowAction.objects
        .filter(instance__document_id=expense)
        .select_related('action_status', 'approver_man_number', 'step', 'instance')
        .order_by('actioned_at')
    )

    # 承認予定者（keiri ステップ補完込み）
    try:
        pending_approvers = get_pending_approvers(expense)
    except Exception:
        pending_approvers = []

    dynamic_fields_display = _build_dynamic_fields_display(expense)
    progress = _get_step_progress_map([expense.document_id]).get(expense.document_id)

    return render(request, 'expenses/settings_approval_detail.html', {
        'expense': expense,
        'workflow_actions': workflow_actions,
        'pending_approvers': pending_approvers,
        'dynamic_fields_display': dynamic_fields_display,
        'progress': progress,
        'return_qs': request.GET.get('return_qs', ''),
    })


@login_required
def settings_force_action(request, pk):
    """管理: 強制承認・却下・削除"""
    if request.method != 'POST':
        return redirect('expenses:settings_approval_admin')

    expense = get_object_or_404(T_Document, pk=pk)
    action = request.POST.get('action')
    comment = request.POST.get('comment', '').strip()
    return_qs = request.POST.get('return_qs', '')

    if action == 'approve':
        from .models import M_WorkflowStep
        now = timezone.now()

        instance = T_WorkflowInstance.objects.filter(
            document_id=expense
        ).select_related('step', 'workflow_template').order_by('-started_at').first()

        if instance:
            current_order = instance.step_order or (
                instance.step.step_order if instance.step else None
            )

            # ① 現ステップの承認アクションとして記録（action_status は APPROVED）
            approved_st = M_Status.objects.get_or_create(
                status_cd='APPROVED', defaults={'status_name': '回覧中', 'action_name': '承認'}
            )[0]
            T_WorkflowAction.objects.create(
                instance=instance,
                step=instance.step,
                approver_man_number=request.user,
                action_status=approved_st,
                comment=comment or '管理者による強制承認',
            )

            # ② 現ステップの pending T_DocumentApprover を APPROVED に
            T_DocumentApprover.objects.filter(
                document_id=expense,
                step_id=instance.step,
                step_order=current_order,
                status__in=['pending', 'draft'],
            ).update(status='APPROVED', approved_at=now)

            # ③ 次ステップを探す
            next_step = None
            if current_order is not None:
                next_step = (
                    M_WorkflowStep.objects
                    .filter(
                        workflow_template=instance.workflow_template,
                        step_order__gt=current_order,
                    )
                    .order_by('step_order')
                    .first()
                )

            if next_step:
                # ④a 次ステップへ進む（中間承認継続）
                instance.step = next_step
                instance.step_order = next_step.step_order
                instance.save(update_fields=['step', 'step_order'])

                # 中間承認: 文書ステータスは INPRO（申請中）のまま継続
                inpro_st = M_Status.objects.get_or_create(
                    status_cd='INPRO', defaults={'status_name': '申請中', 'action_name': '提出'}
                )[0]
                expense.status_cd = inpro_st
                expense.updated_at = now
                expense.save(update_fields=['status_cd', 'updated_at'])

                # 次ステップの承認者にメール通知
                try:
                    subject, body = _build_approval_request_mail(
                        expense, f"【次の承認ステップ ({next_step.step_order})】"
                    )
                    # T_DocumentApprover に登録済みの承認者を優先
                    next_approvers = T_DocumentApprover.objects.filter(
                        document_id=expense,
                        step_id=next_step,
                        step_order=next_step.step_order,
                    ).select_related('man_number')
                    if next_approvers.exists():
                        for a in next_approvers:
                            to_addr = getattr(a.man_number, 'email', None)
                            if to_addr:
                                send_notification(to_addr.strip(), subject, body)
                    else:
                        # 未登録の場合は candidates_for_step で実際の候補者を探す（keiri ステップ等）
                        candidates = candidates_for_step(expense.man_number, next_step)
                        sent = False
                        for cand in candidates:
                            to_addr = getattr(cand, 'email', None)
                            if to_addr:
                                send_notification(to_addr.strip(), subject, body)
                                sent = True
                        if not sent:
                            # 候補が見つからない場合のみ申請者へ
                            to_addr = getattr(expense.man_number, 'email', None)
                            if to_addr:
                                send_notification(to_addr.strip(), subject, body)
                except Exception:
                    pass
            else:
                # ④b 最終ステップだった → FNS 完了
                fns = M_Status.objects.get_or_create(
                    status_cd='FNS', defaults={'status_name': '承認済み', 'action_name': '承認'}
                )[0]
                instance.status = fns
                instance.completed_at = now
                instance.save(update_fields=['status', 'completed_at'])

                expense.status_cd = fns
                expense.updated_at = now
                expense.save(update_fields=['status_cd', 'updated_at'])

                # 申請者へ最終承認メール
                try:
                    send_notification(
                        expense.man_number.email,
                        "[経費精算] 申請結果（最終承認）",
                        f"申請ID:{expense.document_id} が最終承認されました。\nコメント: {comment or 'なし'}"
                    )
                except Exception:
                    pass

        return redirect('expenses:settings_approval_detail', pk=pk)

    elif action == 'reject':
        now = timezone.now()
        rej = M_Status.objects.get_or_create(
            status_cd='REJECTED', defaults={'status_name': '却下', 'action_name': '却下'}
        )[0]

        # ① 文書ステータスを REJECTED に
        expense.status_cd = rej
        expense.updated_at = now
        expense.save(update_fields=['status_cd', 'updated_at'])

        instance = T_WorkflowInstance.objects.filter(
            document_id=expense
        ).order_by('-started_at').first()

        if instance:
            # ② ワークフローアクション記録
            T_WorkflowAction.objects.create(
                instance=instance,
                step=instance.step,
                approver_man_number=request.user,
                action_status=rej,
                comment=comment or '管理者による却下',
            )
            # ③ 現ステップの T_DocumentApprover を REJECTED に更新
            T_DocumentApprover.objects.filter(
                document_id=expense,
                step_id=instance.step,
                status__in=['pending', 'draft'],
            ).update(status='REJECTED', approved_at=now)

            # ④ ワークフローインスタンスを完了（却下）状態に
            instance.status = rej
            instance.completed_at = now
            instance.save(update_fields=['status', 'completed_at'])

        # ⑤ 申請者へ却下の結果メール
        try:
            send_notification(
                expense.man_number.email,
                "[経費精算] 申請結果（却下）",
                f"申請ID:{expense.document_id} が却下されました。\nコメント: {comment or 'なし'}"
            )
        except Exception:
            pass

        return redirect('expenses:settings_approval_detail', pk=pk)

    elif action == 'delete':
        expense.delete()
        base_url = '/expenses/settings/approval_admin/'
        return redirect(f"{base_url}?{return_qs}" if return_qs else base_url)

    return redirect('expenses:settings_approval_detail', pk=pk)


# ============================================================
#  マスタ設定（汎用CRUD）
# ============================================================

MASTER_REGISTRY = {
    'm_bumon': {
        'model': M_Bumon,
        'list_fields': [('bumon_cd', '部門コード'), ('bumon_name', '部門名')],
        'form_fields': ['bumon_cd', 'bumon_name'],
        'pk_attr': 'bumon_cd',
    },
    'm_post': {
        'model': M_Post,
        'list_fields': [('post_cd', '役職コード'), ('post_name', '役職名'), ('post_order', '職位順')],
        'form_fields': ['post_cd', 'post_name', 'post_order'],
        'pk_attr': 'post_cd',
    },
    'm_account': {
        'model': M_Account,
        'list_fields': [('account_cd', '勘定科目コード'), ('account_name', '勘定科目名')],
        'form_fields': ['account_cd', 'account_name'],
        'pk_attr': 'account_cd',
    },
    'm_status': {
        'model': M_Status,
        'list_fields': [('status_cd', 'コード'), ('status_name', '名称'), ('action_name', 'アクション名'), ('order_by', '表示順')],
        'form_fields': ['status_cd', 'status_name', 'action_name', 'order_by'],
        'pk_attr': 'status_cd',
    },
    'm_item': {
        'model': M_Item,
        'list_fields': [('data_kbn', '区分'), ('key', 'キー'), ('content', '内容'), ('content2', '内容2')],
        'form_fields': ['data_kbn', 'key', 'content', 'content2'],
        'pk_attr': 'pk',
    },
    'm_group': {
        'model': M_Group,
        'list_fields': [('group_cd', '部署コード'), ('group_name', '部署名'), ('upper_group_cd', '上位部署コード')],
        'form_fields': ['group_cd', 'group_name', 'upper_group_cd'],
        'pk_attr': 'group_cd',
    },
    'm_belong_to': {
        'model': M_BelongTo,
        'list_fields': [('man_number', '社員'), ('group_cd', '所属部署')],
        'form_fields': ['man_number', 'group_cd'],
        'pk_attr': 'belong_id',
    },
    'm_workflow_template': {
        'model': M_WorkflowTemplate,
        'list_fields': [('workflow_template_id', 'ID'), ('workflow_template_name', 'テンプレート名'), ('description', '説明')],
        'form_fields': ['workflow_template_name', 'description'],
        'pk_attr': 'workflow_template_id',
    },
    'm_workflow_step': {
        'model': M_WorkflowStep,
        'list_fields': [('step_id', 'ID'), ('workflow_template', 'テンプレート'), ('step_order', '順序'), ('step_type', '種別'), ('allowed_bumon_scope', '部門範囲'), ('approver_post', '承認役職')],
        'form_fields': ['workflow_template', 'step_order', 'step_type', 'allowed_bumon_scope', 'approver_post', 'allowed_post', 'condition_expr', 'group_id'],
        'pk_attr': 'step_id',
    },
    'm_document_group': {
        'model': M_DocumentGroup,
        'list_fields': [('menu_group', 'グループコード'), ('menu_group_name', 'グループ名'), ('category', 'カテゴリ'), ('menu_order', '表示順')],
        'form_fields': ['menu_group', 'menu_group_name', 'category', 'menu_order'],
        'pk_attr': 'menu_group',
    },
    'm_document_type': {
        'model': M_DocumentType,
        'list_fields': [('document_type_id', 'ID'), ('document_type_name', '申請種別名'), ('menu_group', '文書グループ'), ('menu_order', '表示順'), ('workflow_template_id', 'ワークフロー'), ('bumon_scope', '部門スコープ')],
        'form_fields': ['document_type_name', 'description', 'menu_group', 'menu_order', 'workflow_template_id', 'bumon_scope'],
        'pk_attr': 'document_type_id',
    },
    'm_document_field': {
        'model': M_DocumentField,
        'list_fields': [('document_type', '申請種別'), ('field_name', 'フィールド名'), ('field_type', '型'), ('field_order', '順序'), ('col_width', '幅'), ('section_header', 'セクション見出し')],
        'form_fields': ['document_type', 'field_name', 'field_type', 'field_name_view', 'field_order', 'col_width', 'row_break', 'required', 'placeholder', 'field_help_text', 'calc_formula', 'section_header'],
        'pk_attr': 'pk',
    },
    'm_account_document': {
        'model': M_AccountDocument,
        'list_fields': [('document_type', '申請種別'), ('account_cd', '勘定科目')],
        'form_fields': ['document_type', 'account_cd'],
        'pk_attr': 'pk',
    },
    'm_user': {
        'model': M_User,
        'list_fields': [('man_number', '社員番号'), ('user_name', '氏名'), ('bumon_cd', '部門'), ('post_cd', '役職'), ('role', '権限'), ('is_active', '有効')],
        'form_fields': ['man_number', 'username', 'user_name', 'email', 'bumon_cd', 'post_cd', 'role', 'is_active'],
        'pk_attr': 'pk',
    },
}


def _master_get_form_class(cfg, is_create):
    """ModelFormClassを生成。編集時はユーザー定義PKフィールドを除外。"""
    from django import forms as dj_forms
    form_fields = list(cfg['form_fields'])
    pk_attr = cfg['pk_attr']
    if not is_create and pk_attr != 'pk' and pk_attr in form_fields:
        form_fields = [f for f in form_fields if f != pk_attr]
    return modelform_factory(cfg['model'], fields=form_fields)


def _master_add_bootstrap(form):
    """フォームウィジェットにBootstrapクラスを付与。"""
    from django import forms as dj_forms
    for field in form.fields.values():
        w = field.widget
        cls = w.attrs.get('class', '')
        if isinstance(w, (dj_forms.Select, dj_forms.SelectMultiple)):
            w.attrs['class'] = (cls + ' form-select').strip()
        elif isinstance(w, dj_forms.CheckboxInput):
            w.attrs['class'] = (cls + ' form-check-input').strip()
        else:
            w.attrs['class'] = (cls + ' form-control').strip()
    return form


def _master_get_obj(cfg, pk_str):
    """pk文字列からモデルオブジェクトを取得。"""
    pk_attr = cfg['pk_attr']
    if pk_attr == 'pk':
        return get_object_or_404(cfg['model'], pk=pk_str)
    return get_object_or_404(cfg['model'], **{pk_attr: pk_str})


DATA_VIEW_REGISTRY = {
    'v_document_types': {
        'display_name': '文書種別',
        'source_table': 'm_document_types',
        'description':  '文書種別マスタ ＋ ワークフローテンプレート名',
        'icon':         'fa-file-alt',
        'search_cols':  ['document_type_name', 'menu_group_name', 'category', 'workflow_template_name'],
    },
    'v_account_document': {
        'display_name': '文書種別勘定科目',
        'source_table': 'm_account_document',
        'description':  '文書種別ごとの使用可能勘定科目マッピング',
        'icon':         'fa-link',
        'search_cols':  ['document_type_name', 'account_name'],
    },
    'v_belong_to': {
        'display_name': '所属部署マッピング',
        'source_table': 'm_belong_to',
        'description':  'ユーザーと所属グループの関係',
        'icon':         'fa-sitemap',
        'search_cols':  ['man_number', 'user_name', 'group_name'],
    },
    'v_document_field': {
        'display_name': '文書フィールド定義',
        'source_table': 'm_document_field',
        'description':  '文書種別ごとの動的フィールド定義',
        'icon':         'fa-list',
        'search_cols':  ['document_type_name', 'field_name', 'field_name_view', 'field_type'],
    },
    'v_users': {
        'display_name': 'ユーザー',
        'source_table': 'm_user',
        'description':  'ユーザー ＋ 部門 ＋ 役職',
        'icon':         'fa-users',
        'search_cols':  ['man_number', 'user_name', 'email', 'role', 'bumon_name'],
    },
    'v_workflow_steps': {
        'display_name': 'WFステップ',
        'source_table': 'm_workflow_steps',
        'description':  'ワークフローステップ ＋ テンプレート名 ＋ 役職名',
        'icon':         'fa-project-diagram',
        'search_cols':  ['workflow_template_name', 'step_type', 'allowed_bumon_scope'],
    },
    'v_document_approvers': {
        'display_name': '文書承認予定者',
        'source_table': 't_document_approvers',
        'description':  '文書ごとの承認予定者リスト',
        'icon':         'fa-user-check',
        'search_cols':  ['document_title', 'approver_man_number', 'approver_name', 'status'],
    },
    'v_documentcontents': {
        'display_name': '文書明細',
        'source_table': 't_documentcontents',
        'description':  '文書明細 ＋ 勘定科目名 ＋ 申請種別名',
        'icon':         'fa-receipt',
        'search_cols':  ['document_title', 'document_type_name', 'shiharaisaki', 'purpose', 'account_name'],
    },
    'v_documents': {
        'display_name': '文書（申請）',
        'source_table': 't_documents',
        'description':  '申請文書 ＋ 申請種別 ＋ 申請者 ＋ ステータス',
        'icon':         'fa-folder-open',
        'search_cols':  ['title', 'document_type_name', 'applicant_name', 'status_name', 'charge_bumon_name'],
    },
    'v_feedback': {
        'display_name': '改善要望',
        'source_table': 't_feedback',
        'description':  '改善要望 ＋ 登録者情報',
        'icon':         'fa-comment-alt',
        'search_cols':  ['applicant_name', 'request_text', 'response_text'],
    },
    'v_workflow_actions': {
        'display_name': 'WFアクション',
        'source_table': 't_workflow_actions',
        'description':  '承認・却下・差戻しアクション履歴',
        'icon':         'fa-history',
        'search_cols':  ['approver_man_number', 'approver_name', 'action_status_name', 'comment'],
    },
    'v_workflow_instances': {
        'display_name': 'WFインスタンス',
        'source_table': 't_workflow_instances',
        'description':  '文書ごとのワークフロー実行状況',
        'icon':         'fa-stream',
        'search_cols':  ['document_title', 'document_type_name', 'wf_status_name'],
    },
}


@login_required
def settings_data_view_home(request):
    """データ参照ホーム：全VIEWの一覧"""
    return render(request, 'expenses/settings_data_view_home.html', {
        'views': DATA_VIEW_REGISTRY,
    })


@login_required
def settings_data_view_browse(request, view_name):
    """特定 VIEW の一覧・検索"""
    from django.db import connection as _conn
    if view_name not in DATA_VIEW_REGISTRY:
        raise Http404
    cfg     = DATA_VIEW_REGISTRY[view_name]
    q       = request.GET.get('q', '').strip()
    page    = max(1, int(request.GET.get('page', 1)))
    per_page = 50

    ilike_op = 'ILIKE' if _conn.vendor == 'postgresql' else 'LIKE'

    where_sql, params = '', []
    if q and cfg['search_cols']:
        conds     = ' OR '.join(f"{col} {ilike_op} %s" for col in cfg['search_cols'])
        where_sql = f' WHERE ({conds})'
        params    = [f'%{q}%'] * len(cfg['search_cols'])

    cols, rows, total, view_error = [], [], 0, None
    try:
        with _conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM {view_name}{where_sql}", params)
            total = cur.fetchone()[0]
            offset = (page - 1) * per_page
            cur.execute(
                f"SELECT * FROM {view_name}{where_sql} LIMIT %s OFFSET %s",
                params + [per_page, offset],
            )
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
    except Exception as e:
        view_error = (
            f"ビュー {view_name} を参照できません: {e} | "
            "`python manage.py create_views` で VIEW を作成してください。"
        )

    num_pages = max(1, (total + per_page - 1) // per_page)
    return render(request, 'expenses/settings_data_view.html', {
        'view_name':    view_name,
        'cfg':          cfg,
        'cols':         cols,
        'rows':         rows,
        'total':        total,
        'q':            q,
        'page':         page,
        'num_pages':    num_pages,
        'has_prev':     page > 1,
        'has_next':     page < num_pages,
        'view_error':   view_error,
    })


@login_required
def settings_master_home(request):
    """マスタ設定ホーム: M_Item(data_kbn='MST') からメニュー生成"""
    raw = M_Item.objects.filter(data_kbn='MST').order_by('key')
    masters = [
        {'key': m.content, 'display_name': m.content2, 'in_registry': m.content in MASTER_REGISTRY}
        for m in raw
    ]
    return render(request, 'expenses/settings_master_home.html', {'masters': masters})


@login_required
def settings_master_list(request, master_key):
    """マスタ一覧"""
    from django.db.models import CharField, TextField
    cfg = MASTER_REGISTRY.get(master_key)
    if not cfg:
        raise Http404
    item = M_Item.objects.filter(data_kbn='MST', content=master_key).first()
    display_name = item.content2 if item else master_key

    qs = cfg['model'].objects.all()

    # キーワード検索: list_fields のうち CharField/TextField 列を対象に OR icontains
    q = request.GET.get('q', '').strip()
    if q:
        char_fields = {
            f.name for f in cfg['model']._meta.get_fields()
            if isinstance(f, (CharField, TextField))
        }
        q_conditions = [
            Q(**{f'{fn}__icontains': q})
            for fn, _ in cfg['list_fields']
            if fn in char_fields
        ]
        if q_conditions:
            combined = q_conditions[0]
            for cond in q_conditions[1:]:
                combined |= cond
            qs = qs.filter(combined)

    total_count = qs.count()
    paginator = Paginator(qs, 50)
    page_obj = paginator.get_page(request.GET.get('page', 1))
    pk_attr = cfg['pk_attr']
    list_fields = cfg['list_fields']

    rows = []
    for obj in page_obj:
        pk_val = str(getattr(obj, pk_attr, obj.pk))
        vals = [str(getattr(obj, fn, '') or '') for fn, _ in list_fields]
        rows.append({'pk': pk_val, 'values': vals})

    return render(request, 'expenses/settings_master_list.html', {
        'master_key': master_key,
        'display_name': display_name,
        'headers': [label for _, label in list_fields],
        'rows': rows,
        'page_obj': page_obj,
        'q': q,
        'total_count': total_count,
    })


@login_required
def settings_master_create(request, master_key):
    """マスタ新規作成"""
    cfg = MASTER_REGISTRY.get(master_key)
    if not cfg:
        raise Http404
    item = M_Item.objects.filter(data_kbn='MST', content=master_key).first()
    display_name = item.content2 if item else master_key
    FormClass = _master_get_form_class(cfg, is_create=True)

    if request.method == 'POST':
        form = FormClass(request.POST)
        if form.is_valid():
            form.save()
            return redirect('expenses:settings_master_list', master_key=master_key)
    else:
        form = FormClass()

    _master_add_bootstrap(form)
    return render(request, 'expenses/settings_master_form.html', {
        'master_key': master_key,
        'display_name': display_name,
        'form': form,
        'is_create': True,
    })


@login_required
def settings_master_edit(request, master_key, pk):
    """マスタ編集"""
    cfg = MASTER_REGISTRY.get(master_key)
    if not cfg:
        raise Http404
    obj = _master_get_obj(cfg, pk)
    item = M_Item.objects.filter(data_kbn='MST', content=master_key).first()
    display_name = item.content2 if item else master_key
    FormClass = _master_get_form_class(cfg, is_create=False)

    if request.method == 'POST':
        form = FormClass(request.POST, instance=obj)
        if form.is_valid():
            form.save()
            return redirect('expenses:settings_master_list', master_key=master_key)
    else:
        form = FormClass(instance=obj)

    _master_add_bootstrap(form)
    return render(request, 'expenses/settings_master_form.html', {
        'master_key': master_key,
        'display_name': display_name,
        'form': form,
        'is_create': False,
        'obj': obj,
        'obj_pk': pk,
    })


@login_required
def settings_master_delete(request, master_key, pk):
    """マスタ削除（POSTのみ）"""
    cfg = MASTER_REGISTRY.get(master_key)
    if not cfg:
        raise Http404
    if request.method == 'POST':
        obj = _master_get_obj(cfg, pk)
        try:
            obj.delete()
        except Exception:
            pass
    return redirect('expenses:settings_master_list', master_key=master_key)


# ─── 改善要望 ────────────────────────────────────────────────────────────────

@login_required
def feedback_list(request):
    from .models import T_Feedback
    feedbacks = T_Feedback.objects.select_related('man_number').all()
    keyword = request.GET.get('keyword', '').strip()
    status_filter = request.GET.get('status', '')
    if keyword:
        feedbacks = feedbacks.filter(
            models.Q(request_text__icontains=keyword) |
            models.Q(response_text__icontains=keyword)
        )
    if status_filter:
        feedbacks = feedbacks.filter(status_cd=status_filter)
    return render(request, 'expenses/feedback_list.html', {
        'feedbacks': feedbacks,
        'keyword': keyword,
        'status_filter': status_filter,
        'status_choices': T_Feedback.STATUS_CHOICES,
    })


@login_required
def feedback_create(request):
    from .models import T_Feedback
    if request.method == 'POST':
        request_text = request.POST.get('request_text', '').strip()
        if request_text:
            fb = T_Feedback.objects.create(
                man_number=request.user,
                request_text=request_text,
                status_cd='00',
            )
            # スーパーユーザー全員にメール通知
            _feedback_notify_superusers(fb, request.user)
            return redirect('expenses:feedback_list')
        error = '要望事項を入力してください。'
        return render(request, 'expenses/feedback_form.html', {'error': error, 'mode': 'create'})
    return render(request, 'expenses/feedback_form.html', {'mode': 'create'})


def _feedback_notify_superusers(fb, submitter):
    from .utils import send_notification
    superusers = M_User.objects.filter(is_superuser=True).exclude(email__isnull=True).exclude(email='')
    subject = '【改善要望】#' + str(fb.feedback_id) + ' 新規登録'
    message = (
        '改善要望が登録されました。\n\n'
        '要望ID : #' + str(fb.feedback_id) + '\n'
        '登録者 : ' + str(getattr(submitter, 'user_name', submitter)) + '\n'
        '登録日 : ' + str(fb.created_at) + '\n'
        '要望事項:\n' + str(fb.request_text) + '\n\n'
        '回答・状況の更新はシステムからお願いします。'
    )
    for su in superusers:
        send_notification(su.email, subject, message)


@login_required
def feedback_detail(request, pk):
    from .models import T_Feedback
    fb = get_object_or_404(T_Feedback, pk=pk)
    is_admin = bool(request.user.is_superuser)
    return render(request, 'expenses/feedback_detail.html', {'fb': fb, 'is_admin': is_admin})


@login_required
def feedback_edit(request, pk):
    from .models import T_Feedback
    fb = get_object_or_404(T_Feedback, pk=pk)
    is_admin = request.user.is_superuser
    is_owner = (fb.man_number_id == request.user.man_number)
    if not is_admin and not is_owner:
        raise PermissionDenied()

    if request.method == 'POST':
        request_text = request.POST.get('request_text', '').strip()
        response_text = request.POST.get('response_text', '').strip()
        status_cd = request.POST.get('status_cd', fb.status_cd)
        if not request_text:
            return render(request, 'expenses/feedback_form.html', {
                'fb': fb, 'mode': 'edit', 'is_admin': is_admin,
                'status_choices': T_Feedback.STATUS_CHOICES,
                'error': '要望事項を入力してください。',
            })
        fb.request_text = request_text
        if is_admin:
            fb.response_text = response_text
            if status_cd in dict(T_Feedback.STATUS_CHOICES):
                fb.status_cd = status_cd
        fb.save()
        return redirect('expenses:feedback_detail', pk=fb.pk)

    return render(request, 'expenses/feedback_form.html', {
        'fb': fb,
        'mode': 'edit',
        'is_admin': is_admin,
        'status_choices': T_Feedback.STATUS_CHOICES,
    })


@login_required
def feedback_delete(request, pk):
    from .models import T_Feedback
    fb = get_object_or_404(T_Feedback, pk=pk)
    is_admin = request.user.is_superuser
    is_owner = (fb.man_number_id == request.user.man_number)
    if not is_admin and not is_owner:
        raise PermissionDenied()
    if request.method == 'POST':
        fb.delete()
        return redirect('expenses:feedback_list')
    return redirect('expenses:feedback_detail', pk=pk)

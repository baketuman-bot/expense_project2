from django.db.models import Subquery, OuterRef, Exists, Q
from .models import M_DocumentGroup, T_DocumentApprover, T_Document, T_WorkflowInstance, T_DocumentContent


def sidebar_context(request):
    if not request.user.is_authenticated:
        return {}

    groups = (
        M_DocumentGroup.objects
        .filter(category='expense')
        .prefetch_related('document_types')
        .order_by('menu_order')
    )

    sidebar_groups = []
    for grp in groups:
        dt_list = list(grp.document_types.order_by('menu_order'))
        if dt_list:
            sidebar_groups.append((grp, dt_list))

    # 承認待ち件数: 自分が現在のワークフローステップの担当者（pending）として
    # 登録されており、かつ INPRO 状態の申請数
    # has_role('approver') は INPRO 全件を対象（特権）
    pending_approval_count = 0
    try:
        if request.user.has_role('approver'):
            pending_approval_count = T_Document.objects.filter(
                status_cd__status_cd='INPRO'
            ).count()
        else:
            # current_step_subq は is_my_turn (T_DocumentApprover) の内側で評価されるため
            # OuterRef('document_id') = T_DocumentApprover.document_id を参照する
            current_step_subq = T_WorkflowInstance.objects.filter(
                document_id=OuterRef('document_id')  # T_DocumentApprover.document_id
            ).order_by('-started_at').values('step_id')[:1]

            is_my_turn = T_DocumentApprover.objects.filter(
                document_id=OuterRef('pk'),           # T_Document.pk
                man_number=request.user,
                status='pending',
                step_id=Subquery(current_step_subq),  # 現在のステップと一致するか
            )

            pending_approval_count = T_Document.objects.filter(
                status_cd__status_cd='INPRO'
            ).filter(Exists(is_my_turn)).count()
    except Exception:
        pass

    # 精算処理待ち件数: FNS かつ settle_kbn が未設定または _PRE 状態の明細
    settlement_pending_count = 0
    try:
        settlement_pending_count = T_DocumentContent.objects.filter(
            document__status_cd_id='FNS'
        ).filter(
            Q(settle_kbn__isnull=True) | Q(settle_kbn__endswith='_PRE')
        ).count()
    except Exception:
        pass

    can_manage_assets = False
    try:
        can_manage_assets = request.user.has_role('accountant') or request.user.has_role('admin')
    except Exception:
        pass

    return {
        'sidebar_expense_groups': sidebar_groups,
        'pending_approval_count': pending_approval_count,
        'settlement_pending_count': settlement_pending_count,
        'can_manage_assets': can_manage_assets,
    }

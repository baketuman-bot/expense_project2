from django.core.mail import send_mail
from django.conf import settings
from django.db.models import Q, Subquery
from .models import M_User, M_BelongTo, V_Group, M_WorkflowStep

def send_notification(to_email, subject, message):
    if not to_email:
        return
    send_mail(
        subject, message,
        settings.DEFAULT_FROM_EMAIL,
        [to_email], fail_silently=True
    )

def _applicant_groups(applicant: M_User):
    return list(M_BelongTo.objects.filter(man_number=applicant).values_list('group_cd', flat=True))

def _related_groups(group_cds):
    if not group_cds:
        return []
    return list(V_Group.objects.filter(group_cd__in=group_cds).values_list('relation_group_cd', flat=True))

def candidates_for_step(applicant: M_User, step: M_WorkflowStep):
    """allowed_bumon_scope と approver_post の条件から候補者を返す。
    前提: M_Post.post_order は値が小さいほど上位。指定職位以上（post_order <= 指定値）を候補とする。
    """
    qs = M_User.objects.all()

    # 役職条件
    if step.approver_post:
        threshold = step.approver_post.post_order
        qs = qs.filter(post_cd__post_order__lte=threshold)

    # 自分自身は除外
    qs = qs.exclude(pk=applicant.pk)

    scope = str(step.allowed_bumon_scope or 'any').strip().lower()
    if scope == 'same':
        # ユーザー要件のSQLに準拠:
        # 候補uの所属(b.group_cd)に対し、v_groupで g.group_cd=b.group_cd かつ g.relation_group_cd が申請者の所属(bb.group_cd) に一致するもの
        # -> 申請者の所属グループを取得
        applicant_group_cds = M_BelongTo.objects.filter(man_number=applicant).values('group_cd__group_cd')
        # -> 申請者所属に紐づく g.group_cd を取得（relationが申請者側）
        candidate_group_cds = V_Group.objects.filter(
            relation_group_cd__in=Subquery(applicant_group_cds)
        ).values('group_cd')
        # -> 候補ユーザーは、その所属が上記 group_cd に含まれる
        qs = qs.filter(belongs__group_cd__group_cd__in=Subquery(candidate_group_cds)).distinct()
    elif scope == 'keiri':
        # 経理系ロール（自動回付想定）
        qs = qs.filter(role__in=['accountant', 'final_approver'])
    elif scope == 'parent':
        # 未定義のため、最小限: 自部門と同系列（v_group を親方向に解釈できるなら拡張）。当面は any と同等で返す。
        pass
    else:
        # any: 組織条件なし
        pass

    return qs.order_by('post_cd__post_order', 'user_name').distinct()

def steps_with_candidates(applicant: M_User, workflow_template):
    steps = workflow_template.steps.all().order_by('step_order')
    data = []
    for s in steps:
        cands = candidates_for_step(applicant, s)
        scope_norm = str(s.allowed_bumon_scope or 'any').strip().lower()
        data.append({
            'step_id': s.pk,
            'step_order': s.step_order,
            'step_type': s.step_type,
            'allowed_bumon_scope': scope_norm,
            'approver_post_cd': s.approver_post.post_cd if s.approver_post else None,
            'approver_post_name': s.approver_post.post_name if s.approver_post else None,
            'candidates': [{
                'man_number': u.man_number,
                'user_name': u.user_name,
                'post_name': (u.post_cd.post_name if u.post_cd else ''),
                'bumon_cd': (u.bumon_cd.bumon_cd if u.bumon_cd else ''),
                'bumon_name': (u.bumon_cd.bumon_name if u.bumon_cd else ''),
            } for u in cands],
        })
    return data

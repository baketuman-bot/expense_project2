from django.core.mail import send_mail
from django.conf import settings
from django.db.models import Q, Subquery
from .models import M_User, M_BelongTo, V_Group, M_WorkflowStep

def _resolve_recipient(to_email: str | None):
    # 開発中は強制送信先を優先
    forced = getattr(settings, 'EMAIL_FORCE_TO', '')
    if forced:
        return forced
    return to_email

def send_notification(to_email, subject, message):
    final_to = _resolve_recipient(to_email)
    if not final_to:
        return
    try:
        sent = send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            [final_to],
            fail_silently=False,
        )
        if not sent:
            print(f"[mail][WARN] Not sent (backend returned 0). to={final_to} subj={subject}")
            print(message)
    except Exception as e:
        # エラーをサーバーログへ出力（開発時のトラブルシュート用）
        print(f"[mail][ERROR] to={final_to} subj={subject} err={e}")
        print("---- message ----\n" + str(message) + "\n-----------------")
        # 非ASCII文字を含む場合のヒント
        try:
            subject.encode('ascii')
            message.encode('ascii')
        except Exception:
            print("[mail][HINT] 件名/本文に非ASCII(日本語)が含まれます。サーバー側のMTAが7bitのみの場合は送れない可能性があります。")

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
        # 候補グループの抽出ロジック（指定SQL準拠）:
        #   SELECT gg.group_cd FROM v_group gg
        #   WHERE gg.relation_group_cd IN (
        #       SELECT g.relation_group_cd FROM v_group g
        #       WHERE g.group_cd = '申請者の所属グループ'
        #   )
        # 意味: 申請者グループが属する上位組織群を共通祖先に持つ全グループ
        #       = 申請者グループ・兄弟グループ・その配下グループが候補範囲
        # 申請者の所属グループを取得
        applicant_group_cds = M_BelongTo.objects.filter(man_number=applicant).values('group_cd__group_cd')
        # Inner: 申請者グループの relation_group_cd（上位組織＋自身）を取得
        inner_cds = V_Group.objects.filter(
            group_cd__in=Subquery(applicant_group_cds)
        ).exclude(relation_group_cd='').values('relation_group_cd')
        # Outer: inner の relation_group_cd を持つ group_cd を取得
        #        = 申請者と共通の上位組織に属する全グループ
        target_group_cds = V_Group.objects.filter(
            relation_group_cd__in=Subquery(inner_cds)
        ).exclude(relation_group_cd='').values('group_cd')
        # 候補ユーザーは target_group_cds に所属する
        qs = qs.filter(belongs__group_cd__group_cd__in=Subquery(target_group_cds)).distinct()
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


def get_pending_approvers(document):
    """承認予定者（未処理）一覧を返す。

    T_DocumentApprover に登録済みの pending/draft 行に加え、
    M_WorkflowStep の allowed_bumon_scope='keiri' で、まだ APPROVED アクションが
    行われていない経理ステップを補完して返す。

    テンプレートが参照する属性: step_order / man_number.user_name /
    man_number.post_cd.post_name
    """
    from types import SimpleNamespace
    from .models import T_DocumentApprover, T_WorkflowAction, M_WorkflowStep

    explicit = list(
        T_DocumentApprover.objects
        .filter(document_id=document, status__in=['pending', 'draft'])
        .select_related('man_number', 'man_number__post_cd', 'step_id')
    )

    doc_type = getattr(document, 'document_type', None)
    tpl = getattr(doc_type, 'workflow_template_id', None) if doc_type else None
    if not tpl:
        return sorted(explicit, key=lambda x: x.step_order or 0)

    keiri_steps = list(
        M_WorkflowStep.objects
        .filter(workflow_template=tpl, allowed_bumon_scope='keiri')
        .select_related('approver_post')
        .order_by('step_order')
    )
    if not keiri_steps:
        return sorted(explicit, key=lambda x: x.step_order or 0)

    covered_step_ids = {pa.step_id_id for pa in explicit if pa.step_id_id}
    done_step_ids = set(
        T_WorkflowAction.objects
        .filter(instance__document_id=document, action_status_id='APPROVED')
        .values_list('step_id', flat=True)
    )

    applicant = document.man_number
    extras = []
    for step in keiri_steps:
        if step.step_id in covered_step_ids or step.step_id in done_step_ids:
            continue
        cand = candidates_for_step(applicant, step).first()
        if cand:
            post_ns = SimpleNamespace(
                post_name=(cand.post_cd.post_name if cand.post_cd else '')
            ) if cand.post_cd else None
            user_ns = SimpleNamespace(user_name=cand.user_name, post_cd=post_ns)
        else:
            post_ns = SimpleNamespace(
                post_name=step.approver_post.post_name
            ) if step.approver_post else None
            user_ns = SimpleNamespace(user_name='経理担当', post_cd=post_ns)
        extras.append(SimpleNamespace(
            step_order=step.step_order,
            man_number=user_ns,
        ))

    combined = explicit + extras
    return sorted(combined, key=lambda x: x.step_order or 0)

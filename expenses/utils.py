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

    scope が 'same' / 'any' の場合:
        post_order <= step.approver_post.post_order（同等以上の役職）で絞り込む。
    scope が上記以外の場合:
        step.allowed_bumon_scope == M_User.role かつ
        user.post_order < step.approver_post.post_order（要求役職より上位）のユーザーを候補とする。
        （M_Post.post_order は値が小さいほど上位）
    """
    qs = M_User.objects.all()

    # 自分自身は除外
    qs = qs.exclude(pk=applicant.pk)

    scope = str(step.allowed_bumon_scope or 'any').strip().lower()

    if scope == 'same':
        # 役職条件（同等以上: post_order <= threshold）
        if step.approver_post:
            threshold = step.approver_post.post_order
            qs = qs.filter(post_cd__post_order__lte=threshold)
        # グループ条件:
        #   SELECT gg.group_cd FROM v_group gg
        #   WHERE gg.relation_group_cd IN (
        #       SELECT g.relation_group_cd FROM v_group g
        #       WHERE g.group_cd = '申請者の所属グループ'
        #   )
        # = 申請者グループと共通の上位組織に属する全グループ
        applicant_group_cds = M_BelongTo.objects.filter(man_number=applicant).values('group_cd__group_cd')
        inner_cds = V_Group.objects.filter(
            group_cd__in=Subquery(applicant_group_cds)
        ).exclude(relation_group_cd='').values('relation_group_cd')
        target_group_cds = V_Group.objects.filter(
            relation_group_cd__in=Subquery(inner_cds)
        ).exclude(relation_group_cd='').values('group_cd')
        qs = qs.filter(belongs__group_cd__group_cd__in=Subquery(target_group_cds)).distinct()

    elif scope == 'any':
        # 組織条件なし、役職条件のみ（同等以上）
        if step.approver_post:
            threshold = step.approver_post.post_order
            qs = qs.filter(post_cd__post_order__lte=threshold)

    else:
        # 'same'/'any' 以外:
        #   user.role == scope  かつ
        #   user.post_order < step.approver_post.post_order（要求役職より厳密に上位）
        qs = qs.filter(role=scope)
        if step.approver_post:
            threshold = step.approver_post.post_order
            qs = qs.filter(post_cd__post_order__lt=threshold)

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

    T_DocumentApprover に登録済みの pending/draft 行を返す。
    keiri スコープのステップは複数候補者が登録されている場合でも
    「経理部門」として1エントリに集約して返す。

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
    keiri_step_ids = {s.step_id for s in keiri_steps}
    keiri_step_map = {s.step_id: s for s in keiri_steps}

    done_step_ids = set(
        T_WorkflowAction.objects
        .filter(instance__document_id=document, action_status_id='APPROVED')
        .values_list('step_id', flat=True)
    )

    # explicit リストを処理:
    #   keiri ステップ → step_id ごとに「経理部門」として1エントリに集約
    #   非 keiri ステップ → そのまま返す
    result = []
    seen_keiri_step_ids = set()
    for pa in explicit:
        sid = pa.step_id_id
        if sid in keiri_step_ids:
            if sid not in seen_keiri_step_ids:
                seen_keiri_step_ids.add(sid)
                step_obj = keiri_step_map.get(sid)
                post_ns = SimpleNamespace(
                    post_name=(step_obj.approver_post.post_name if step_obj and step_obj.approver_post else '')
                )
                user_ns = SimpleNamespace(user_name='経理部門', last_name='経理部門', post_cd=post_ns)
                result.append(SimpleNamespace(
                    step_order=pa.step_order,
                    man_number=user_ns,
                ))
        else:
            result.append(pa)

    # keiri ステップで T_DocumentApprover 未登録のもの（フォールバック補完）
    covered_step_ids = {pa.step_id_id for pa in explicit if pa.step_id_id}
    for step in keiri_steps:
        if step.step_id in covered_step_ids or step.step_id in done_step_ids:
            continue
        post_ns = SimpleNamespace(
            post_name=(step.approver_post.post_name if step.approver_post else '')
        )
        user_ns = SimpleNamespace(user_name='経理部門', post_cd=post_ns)
        result.append(SimpleNamespace(
            step_order=step.step_order,
            man_number=user_ns,
        ))

    return sorted(result, key=lambda x: x.step_order or 0)

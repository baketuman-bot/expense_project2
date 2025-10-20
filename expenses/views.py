from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from .models import (
    M_User, M_Status, M_Account, T_Document, T_DocumentContent,
    M_Group, M_Bumon, M_Item, M_DocumentType
)
from .forms import ExpenseDetailFormSet, ExpenseDetailEditFormSet, ApprovalForm
from .utils import send_notification, steps_with_candidates
from django.utils import timezone
import uuid
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse, HttpResponseBadRequest

@login_required
def home(request):
    # ログインユーザーの申請を取得
    your_expenses = T_Document.objects.filter(
        man_number=request.user
    ).order_by('-created_at')[:5]  # 最新5件

    # 承認待ちの申請を取得（承認者の場合）
    pending_approvals = T_Document.objects.filter(
        status_cd__status_cd='SUB'
    ).order_by('created_at')[:5]

    context = {
        'user': request.user,
        'your_expenses': your_expenses,
        'pending_approvals': pending_approvals,
    }
    return render(request, "expenses/home.html", context)

@login_required
def expense_list(request):
    expenses = T_Document.objects.filter(man_number=request.user).order_by("-created_at")
    return render(request, "expenses/expense_list.html", {"expenses": expenses})

@login_required
def expense_detail(request, pk):
    expense = get_object_or_404(T_Document, pk=pk)
    
    # 取り消し処理
    if request.method == "POST" and "cancel_expense" in request.POST:
        if expense.man_number == request.user and expense.status_cd.status_cd == "SUB":
            # ステータスを「取り消し」に変更
            try:
                cancelled_status = M_Status.objects.get(status_cd="CAN")
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
                    status_cd="CAN",
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

    return render(request, "expenses/expense_detail.html", {"expense": expense, "workflow_actions": workflow_actions})

@login_required
def expense_edit(request, pk):
    expense = get_object_or_404(T_Document, pk=pk)
    
    # 権限チェック：申請者のみ編集可能
    #   編集可能ステータス: 提出中(SUB) / 下書き(DRA) / 差戻し(RET)
    if expense.man_number != request.user or expense.status_cd.status_cd not in ("SUB", "DRA", "RET"):
        return redirect('expenses:expense_detail', pk=pk)
    
    # エラーメッセージの初期化（未定義参照を防ぐ）
    error_message = None
    
    if request.method == "POST":
        action = request.POST.get('action') or 'save'  # 'save' or 'submit'
        formset = ExpenseDetailEditFormSet(request.POST, request.FILES, queryset=expense.contents.all())
        
        if formset.is_valid():
            try:
                # 申請情報（備考・負担部門の更新）
                memo = request.POST.get('memo')
                if memo is not None:
                    expense.memo = memo[:200]
                bumon_cd_val = request.POST.get('bumon_cd')
                if bumon_cd_val:
                    try:
                        expense.bumon_cd = M_Bumon.objects.get(bumon_cd=bumon_cd_val)
                    except M_Bumon.DoesNotExist:
                        pass
                # 承認者設定はワークフロー側に委ねるためここでは扱わない

                # モデル検証（pay_kbn の妥当性など）
                try:
                    expense.full_clean()
                except Exception:
                    pass

                expense.save()

                # 既存の明細は更新、新規は追加、削除指定の添付のみ削除
                from .models import T_DocumentAttachment, T_DocumentContent
                # 1) 添付の削除（チェックされたもの）
                delete_ids = set(request.POST.getlist('delete_attachments'))
                if delete_ids:
                    T_DocumentAttachment.objects.filter(attachment_id__in=delete_ids).delete()

                # 2) 明細の保存（フォームセットの各行）
                for form in formset.forms:
                    if not (form.is_valid() and form.cleaned_data):
                        continue
                    detail = form.save(commit=False)
                    detail.document = expense
                    # 既存 or 新規の区別（hidden の id で判定）
                    instance_id = form.cleaned_data.get('id') or getattr(form.instance, 'pk', None)
                    if instance_id:
                        # 既存更新
                        detail.document_detail_id = instance_id.document_detail_id if hasattr(instance_id, 'document_detail_id') else instance_id
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
                
                # 提出ボタン押下時は SUB へ状態遷移し、ワークフローを生成
                if action == 'submit':
                    # ステータスを SUB に
                    try:
                        sub_status = M_Status.objects.get(status_cd="SUB")
                    except M_Status.DoesNotExist:
                        sub_status = M_Status.objects.create(status_cd="SUB", status_name="申請中", action_name="提出")
                    expense.status_cd = sub_status
                    expense.save()

                    # 既にインスタンスがなければ作成
                    try:
                        from .models import T_WorkflowInstance, T_DocumentApprover, M_WorkflowStep, M_User, T_WorkflowAction
                        doc_type = expense.document_type
                        exists_instance = T_WorkflowInstance.objects.filter(document_id=expense).exists()
                        if doc_type and doc_type.workflow_template_id and not exists_instance:
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
                            # インスタンス自体の状態は SUB と同義の進行とみなす（WF_INPROGRESS は使用しない）
                            wf_status = sub_status
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
                            # 経理ステップだけは自動回付
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
                                        # 候補取得や作成失敗は致命ではないので無視
                                        pass
                        elif exists_instance:
                            # 既存インスタンスがある場合も SUB を履歴に記録
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
                            except Exception:
                                pass
                    except Exception as e:
                        print("Workflow create on edit error:", str(e))

                return redirect('expenses:expense_detail', pk=pk)
            except Exception as e:
                print("Edit error:", str(e))
                error_message = f"編集中にエラーが発生しました: {str(e)}"
        else:
            # バリデーションエラー時のメッセージ
            error_message = "入力内容にエラーがあります。各明細のエラーメッセージを確認してください。"
    else:
        formset = ExpenseDetailEditFormSet(queryset=expense.contents.all())
        error_message = None
    
    # 申請情報のドロップダウン用データ
    groups = M_Group.objects.all().order_by('group_cd')
    bumons = M_Bumon.objects.all().order_by('bumon_cd')
    pay_items = M_Item.objects.filter(data_kbn='pay').order_by('key')

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
            # 後勝ちでOK（同一ステップ複数は想定しない）
            selected_map[getattr(a.step_id, 'step_id', None)] = getattr(a.man_number, 'man_number', None)
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

    return render(request, "expenses/expense_edit.html", {
        "formset": formset,
        "expense": expense,
        "error_message": error_message,
        "groups": groups,
        "bumons": bumons,
        "pay_items": pay_items,
        "workflow_steps": workflow_steps,
    })

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
        formset = ExpenseDetailFormSet(request.POST, request.FILES)
        print("Formset is valid:", formset.is_valid())
    # 申請情報の取得
        memo = request.POST.get('memo')
        bumon_cd_val = request.POST.get('bumon_cd')
        pay_kbn = request.POST.get('pay_kbn')
    # 旧: 手動承認者選択は廃止（ワークフローステップで管理）
        
        # デバッグ用: 勘定科目の数を確認
        print("Available accounts:", M_Account.objects.count())
        if not formset.is_valid():
            print("Formset errors:", formset.errors)
            error_message = "入力内容にエラーがあります。各明細のエラーメッセージを確認してください。"
            
        if formset.is_valid():
            try:
                with transaction.atomic():
                    # 文書を作成
                    expense = T_Document()
                    expense.man_number = request.user
                    # ステータス（申請=SUB／下書き=DRA）
                    status_code = "DRA" if is_draft else "SUB"
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
                    # タイトル（必須）: 最初の明細の目的から作成、なければデフォルト
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
                    for form in formset.forms:
                        if form.is_valid() and form.cleaned_data:
                            detail = form.save(commit=False)
                            detail.document = expense
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
                                for f in files:
                                    if not f:
                                        continue
                                    T_DocumentAttachment.objects.create(detail=detail, file=f)
                            except Exception as _:
                                pass
                            print("Detail saved:", detail.document_detail_id)
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
                            # インスタンス取得/作成（DRA 状態で保持）
                            dra_inst_status = M_Status.objects.get_or_create(status_cd="DRA", defaults={"status_name": "作成中", "action_name": "下書き"})[0]
                            instance = T_WorkflowInstance.objects.filter(document_id=expense).order_by('-started_at').first()
                            if not instance:
                                instance = T_WorkflowInstance.objects.create(
                                    document_id=expense,
                                    workflow_template=wf,
                                    status=dra_inst_status,
                                    step=first_step,
                                    step_order=(steps[0]['step_order'] if steps else None),
                                )
                            # アクション（DRA）を記録
                            dra_action_status = M_Status.objects.get_or_create(status_cd="DRA", defaults={"status_name": "作成中", "action_name": "下書き"})[0]
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
    else:
        formset = ExpenseDetailFormSet(queryset=T_DocumentContent.objects.none())
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
    bumons = M_Bumon.objects.all().order_by('bumon_cd')
    pay_items = M_Item.objects.filter(data_kbn='pay').order_by('key')
    
    # 承認候補 UI 用データ（GET/POST で同じ構造を出す）
    workflow_steps = []
    try:
        # 表示時の承認候補 UI: 引数の DocType を優先
        doc_type = None
        if document_type_id:
            doc_type = M_DocumentType.objects.filter(document_type_id=document_type_id).first()
        if not doc_type:
            doc_type = M_DocumentType.objects.filter(document_type_name="経費精算書").first()
        if doc_type and doc_type.workflow_template_id:
            workflow_steps = steps_with_candidates(request.user, doc_type.workflow_template_id)
    except Exception:
        workflow_steps = []

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

    return render(request, "expenses/expense_form.html", {
        "formset": formset,
        "error_message": error_message,
        "groups": groups,
        "bumons": bumons,
        "pay_items": pay_items,
        "submission_id": submission_id if request.method == "GET" else request.POST.get('submission_id'),
        "workflow_steps": workflow_steps,
        # サイドメニューからの初回表示時に DocType=1 のWFをダイアログ表示するための値
        "doc1_workflow_template_id": doc1_wf_id,
        "doc1_document_type_name": doc1_name,
        "show_doc1_alert": request.method == "GET",
    })

@login_required
def approval_list(request):
    # 閲覧可能条件:
    #  - 既存ロール (accountant/final_approver/approver)
    #  - もしくは T_DocumentApprover に自分が登録されている場合
    from .models import T_DocumentApprover
    is_role_allowed = request.user.role in ["accountant", "final_approver", "approver"]
    is_listed_as_approver = T_DocumentApprover.objects.filter(man_number=request.user).exists()
    if not (is_role_allowed or is_listed_as_approver):
        raise PermissionDenied()

    # 抽出条件: ステータス SUB または APP
    base_qs = T_Document.objects.filter(status_cd__status_cd__in=["SUB", "APP"])  # 申請中・回覧中

    # 表示対象: 部門一致 or 自分が承認者に登録されている文書
    approver_docs = T_DocumentApprover.objects.filter(man_number=request.user).values_list('document_id', flat=True)
    approvals = base_qs.filter(
        Q(man_number__bumon_cd=request.user.bumon_cd) | Q(document_id__in=approver_docs)
    ).order_by('-created_at')

    return render(request, "expenses/approval_list.html", {"approvals": approvals})

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
                    "APP": "回覧中",
                    "REJ": "却下",
                    "RET": "差し戻し中",
                }
                default_actions = {
                    "APP": "承認",
                    "REJ": "却下",
                    "RET": "差し戻し",
                }
                status = M_Status.objects.create(
                    status_cd=status_code,
                    status_name=default_names.get(status_code, status_code),
                    action_name=default_actions.get(status_code, status_code),
                )
            comment = form.cleaned_data["comment"]
            # 状態更新とワークフローアクションに記録
            expense.status_cd = status
            expense.save()
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
                    if status.status_cd == 'APP':
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
                                target.status = 'APP'
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
                    elif status.status_cd == 'REJ':
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
                                target.status = 'REJ'
                                target.approved_at = now
                                if getattr(target.man_number, 'man_number', None) != getattr(request.user, 'man_number', None):
                                    who = f"{getattr(request.user, 'user_name', '')}({getattr(request.user, 'man_number', '')})"
                                    target.remarks = (target.remarks + "\n" if target.remarks else "") + f"実行者: {who}"
                                target.save()
                        except Exception:
                            pass

                        try:
                            instance.status = status  # REJ
                            instance.completed_at = now
                            instance.save(update_fields=['status', 'completed_at'])
                            expense.status_cd = status  # REJ
                            expense.updated_at = now
                            expense.save(update_fields=['status_cd', 'updated_at'])
                        except Exception:
                            pass
                    elif status.status_cd == 'RET':
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
                                target.status = 'RET'
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
                            instance.status = status  # RET（差し戻し中）
                            instance.save(update_fields=['step', 'step_order', 'status'])
                            expense.status_cd = status
                            expense.updated_at = now
                            expense.save(update_fields=['status_cd', 'updated_at'])
                        except Exception:
                            pass
            except Exception:
                pass
            send_notification(
                expense.man_number.email,
                "[経費精算] 申請結果",
                f"申請ID:{expense.document_id} の結果: {status.status_name}\nコメント: {comment or 'なし'}"
            )
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

    return render(request, "expenses/approval_detail.html", {"expense": expense, "form": form, "workflow_actions": workflow_actions})


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

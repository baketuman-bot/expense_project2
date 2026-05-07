from django.core.management.base import BaseCommand
from django.db import transaction
from expenses.models import T_Document, M_Status, T_WorkflowInstance, M_WorkflowStep


class Command(BaseCommand):
    help = (
        "中間承認状態（status_cd='APPROVED' で最終ステップ未到達）の T_Document を "
        "INPRO に修正する。新ステータス運用（中間=INPRO・最終=FNS）への移行用コマンド。"
    )

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='変更せず対象だけ表示')

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        inpro = M_Status.objects.get_or_create(
            status_cd='INPRO',
            defaults={'status_name': '申請中', 'action_name': '提出'},
        )[0]

        # APPROVED 状態の文書を取得
        targets = T_Document.objects.filter(status_cd__status_cd='APPROVED').select_related('document_type')
        total = targets.count()
        self.stdout.write(f"対象候補: {total}件 (status_cd='APPROVED')")

        updated, skipped = 0, 0
        for doc in targets:
            inst = (T_WorkflowInstance.objects
                    .filter(document_id=doc)
                    .order_by('-started_at')
                    .first())
            if not inst:
                # ワークフローインスタンス無 → 旧データだが安全のため INPRO に直す
                self.stdout.write(f"  doc#{doc.document_id}: instance無 → INPRO に変更")
                if not dry_run:
                    doc.status_cd = inpro
                    doc.save(update_fields=['status_cd'])
                updated += 1
                continue

            # 終端状態のインスタンスはスキップ（FNS/REJECTED/RETURNED）
            inst_status = inst.status.status_cd if inst.status else None
            if inst_status in ('FNS', 'REJECTED', 'RETURNED'):
                self.stdout.write(self.style.WARNING(
                    f"  doc#{doc.document_id}: instance.status={inst_status} のためスキップ（要手動確認）"
                ))
                skipped += 1
                continue

            # 現ステップが最終かどうかチェック
            current_order = inst.step_order or (inst.step.step_order if inst.step else None)
            has_next = False
            if current_order is not None and inst.workflow_template_id:
                has_next = M_WorkflowStep.objects.filter(
                    workflow_template_id=inst.workflow_template_id,
                    step_order__gt=current_order,
                ).exists()

            if has_next:
                self.stdout.write(f"  doc#{doc.document_id}: 中間ステップ(step_order={current_order}) → INPRO")
                if not dry_run:
                    doc.status_cd = inpro
                    doc.save(update_fields=['status_cd'])
                updated += 1
            else:
                self.stdout.write(self.style.WARNING(
                    f"  doc#{doc.document_id}: 最終ステップ(step_order={current_order}) のためスキップ（FNSへの修正は手動で）"
                ))
                skipped += 1

        if dry_run:
            self.stdout.write(self.style.SUCCESS(f"--dry-run: 変更{updated}件 / スキップ{skipped}件"))
        else:
            self.stdout.write(self.style.SUCCESS(f"完了: 変更{updated}件 / スキップ{skipped}件"))

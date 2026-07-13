from django.core.management.base import BaseCommand
from django.db import transaction
from django.contrib.auth import get_user_model

from expenses.models import (
    M_Status, M_Bumon, M_Post, M_Group, M_Account, M_Item,
    M_WorkflowTemplate, M_WorkflowStep, M_DocumentType, M_BelongTo, M_UserRole,
)


class Command(BaseCommand):
    help = "Load initial master data for production. Idempotent: inserts only when missing."

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true", help="Insert even if some records exist (upsert)")

    @transaction.atomic
    def handle(self, *args, **options):
        force = options.get("force", False)
        created_total = 0

        # 1) Statuses
        statuses = [
            ("DRAFT",    "申請前",   None,       10),
            ("INPRO",    "申請中",   None,       20),
            ("RETURNED", "差戻し",   "RETURNED", 30),
            ("REJECTED", "却下",     "REJECTED", 40),
            ("APPROVED", "承認済",   "APPROVED", 50),
            ("CANCEL",   "取り下げ", "取消し",   90),
        ]
        for cd, name, action, order in statuses:
            obj, created = M_Status.objects.update_or_create(
                status_cd=cd,
                defaults={"status_name": name, "action_name": action, "order_by": order},
            )
            created_total += int(created)

        # 2) Posts
        posts = [
            ("EMP", "一般社員", 100),
            ("MGR", "部長", 10),
        ]
        for cd, name, order in posts:
            obj, created = M_Post.objects.update_or_create(
                post_cd=cd, defaults={"post_name": name, "post_order": order}
            )
            created_total += int(created)

        # 3) Bumon (Departments)
        bumons = [
            ("SALES", "営業部"),
            ("ADMIN", "管理部"),
        ]
        for cd, name in bumons:
            obj, created = M_Bumon.objects.update_or_create(
                bumon_cd=cd, defaults={"bumon_name": name}
            )
            created_total += int(created)

        # 4) Groups
        groups = [
            ("GRP_SALES", "営業部"),
            ("GRP_ADMIN", "管理部"),
        ]
        for cd, name in groups:
            obj, created = M_Group.objects.update_or_create(
                group_cd=cd, defaults={"group_name": name, "upper_group_cd": None}
            )
            created_total += int(created)

        # 5) Accounts
        accounts = [
            ("TRAVEL", "旅費交通費"),
            ("SUPPLIES", "消耗品費"),
        ]
        for cd, name in accounts:
            obj, created = M_Account.objects.update_or_create(
                account_cd=cd, defaults={"account_name": name}
            )
            created_total += int(created)

        # 6) Items (minimal)
        items = [
            ("WF", "01", "承認種別", "APPROVED"),
        ]
        for data_kbn, key, content, content2 in items:
            obj, created = M_Item.objects.update_or_create(
                data_kbn=data_kbn,
                key=key,
                defaults={"content": content, "content2": content2},
            )
            created_total += int(created)

        # 7) Workflow Template and Steps
        tpl, _ = M_WorkflowTemplate.objects.get_or_create(
            workflow_template_name="デフォルトフロー",
            defaults={"description": "単段承認フロー"},
        )
        # A simple one-step approval flow by manager (natural key: template + step_order)
        step_defaults = {
            "step_type": "approval",
            "condition_expr": None,
            "approver_post": M_Post.objects.filter(pk="MGR").first(),
            "allowed_post": None,
            "allowed_bumon_scope": "any",
            "group_id": None,
        }
        M_WorkflowStep.objects.update_or_create(
            workflow_template=tpl,
            step_order=1,
            defaults=step_defaults,
        )

        # 8) Document Types
        M_DocumentType.objects.update_or_create(
            document_type_name="経費申請",
            defaults={"description": "汎用経費ワークフロー", "workflow_template_id": tpl},
        )

        # 9) Users (optional seed only when no users)
        User = get_user_model()
        if User.objects.count() == 0 or force:
            # Avoid duplicate usernames
            if not User.objects.filter(username="approver").exists():
                approver = User.objects.create_user(
                    username="approver",
                    password="pass1234",
                    email="approver@example.com",
                    man_number="E0002",
                    user_name="承認者",
                )
                approver.bumon_cd = M_Bumon.objects.filter(pk="ADMIN").first()
                approver.post_cd = M_Post.objects.filter(pk="MGR").first()
                approver.save()
                M_UserRole.objects.get_or_create(man_number=approver, role="approver")

            if not User.objects.filter(username="employee").exists():
                employee = User.objects.create_user(
                    username="employee",
                    password="pass1234",
                    email="employee@example.com",
                    man_number="E0003",
                    user_name="一般社員",
                )
                employee.bumon_cd = M_Bumon.objects.filter(pk="SALES").first()
                employee.post_cd = M_Post.objects.filter(pk="EMP").first()
                employee.save()

        # 10) Belong-to mapping (only if users exist)
        for man_number, group_cd in [("E0002", "GRP_ADMIN"), ("E0003", "GRP_SALES")]:
            u = User.objects.filter(man_number=man_number).first()
            g = M_Group.objects.filter(pk=group_cd).first()
            if u and g:
                M_BelongTo.objects.get_or_create(man_number=u, group_cd=g)

        self.stdout.write(self.style.SUCCESS(f"Initial master load done. created/updated ~{created_total} records."))

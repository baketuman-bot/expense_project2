from django.core.management.base import BaseCommand
from django.db import connection
from expenses.view_sqls import ALL_VIEWS


class Command(BaseCommand):
    help = "全 DB VIEW を作成/再作成します（GRANT CREATE VIEW 権限が必要）"

    def handle(self, *args, **options):
        ok = err = 0
        with connection.cursor() as cursor:
            for name, sql in ALL_VIEWS.items():
                try:
                    cursor.execute(sql)
                    self.stdout.write(self.style.SUCCESS(f"  ✓ {name}"))
                    ok += 1
                except Exception as e:
                    self.stderr.write(self.style.ERROR(f"  ✗ {name}: {e}"))
                    err += 1

        self.stdout.write(f"\n完了: 成功 {ok} 件 / 失敗 {err} 件")
        if err:
            self.stderr.write(
                "MySQL の場合は管理者ユーザーで先に以下を実行してください:\n"
                "  GRANT CREATE VIEW ON expense_db.* TO 'ex_user'@'%';\n"
                "  FLUSH PRIVILEGES;"
            )

"""中国輸出Invoice管理: 報告ウィザードで放置された一時バッチディレクトリを削除する。

通常はウィザード側（ステップ1のGET・キャンセル・報告確定）で掃除されるため、
このコマンドはブラウザを閉じるなどで取り残された孤児の回収用。
"""
from django.core.management.base import BaseCommand

from expenses.china_invoice_batch import cleanup_stale_batches


class Command(BaseCommand):
    help = '中国輸出Invoice報告ウィザードの古い一時バッチディレクトリを削除する'

    def add_arguments(self, parser):
        parser.add_argument(
            '--hours', type=int, default=24,
            help='この時間より古いディレクトリを削除する（既定: 24）')
        parser.add_argument(
            '--dry-run', action='store_true', help='削除せず対象件数のみ表示する')

    def handle(self, *args, **options):
        count = cleanup_stale_batches(
            max_age_hours=options['hours'], dry_run=options['dry_run'])
        prefix = '[dry-run] ' if options['dry_run'] else ''
        self.stdout.write(self.style.SUCCESS(f'{prefix}{count}件の一時バッチを削除しました。'))

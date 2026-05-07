from django.core.management.base import BaseCommand
from expenses.models import M_Status


class Command(BaseCommand):
    help = "M_Status の status_name を分かりやすい標準値に更新する（特に APPROVED → 承認中）"

    DEFAULT_NAMES = [
        # (status_cd, status_name, action_name)
        ('DRAFT',    '下書き',    '下書き'),
        ('INPRO',    '申請中',    '提出'),
        ('APPROVED', '承認中',    '承認'),
        ('FNS',      '承認済み',  '承認'),
        ('REJECTED', '却下',      '却下'),
        ('RETURNED', '差戻し中',  '差戻し'),
        ('CANCEL',   '取り下げ',  '取消し'),
    ]

    def handle(self, *args, **options):
        for cd, name, action in self.DEFAULT_NAMES:
            obj, created = M_Status.objects.get_or_create(
                status_cd=cd,
                defaults={'status_name': name, 'action_name': action},
            )
            if created:
                self.stdout.write(self.style.SUCCESS(f"作成: {cd} = '{name}'"))
                continue
            if obj.status_name != name:
                old = obj.status_name
                obj.status_name = name
                obj.save(update_fields=['status_name'])
                self.stdout.write(self.style.SUCCESS(f"更新 {cd}: '{old}' → '{name}'"))
            else:
                self.stdout.write(f"OK   {cd}: '{name}' (変更なし)")
        self.stdout.write(self.style.SUCCESS("完了。"))

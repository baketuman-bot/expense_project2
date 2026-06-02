from django.db import migrations, models


def seed_mail_manage(apps, schema_editor):
    M_MailManage = apps.get_model('expenses', 'M_MailManage')
    entries = [
        ('approval', '承認依頼・次ステップ通知',
         '申請者が提出した際の第1ステップ通知、および中間承認後の次担当者への通知'),
        ('result',   '申請結果通知',
         '最終承認・却下・差戻し完了時に申請者へ送信する通知'),
        ('feedback', 'フィードバック系通知',
         '改善要望の新規登録時に管理者へ送る通知、および状況更新時に登録者へ送る通知'),
    ]
    for cat, label, desc in entries:
        M_MailManage.objects.get_or_create(
            mail_category=cat,
            defaults={'mail_label': label, 'mail_desc': desc, 'enabled': True},
        )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [('expenses', '0064_seed_mailcfg')]

    operations = [
        migrations.CreateModel(
            name='M_MailManage',
            fields=[
                ('mail_category', models.CharField(max_length=20, primary_key=True,
                                                   serialize=False, verbose_name='メールカテゴリ')),
                ('mail_label',    models.CharField(max_length=100, verbose_name='カテゴリ名')),
                ('mail_desc',     models.CharField(blank=True, max_length=255, verbose_name='説明')),
                ('enabled',       models.BooleanField(default=True, verbose_name='送信する')),
            ],
            options={'db_table': 'm_mail_manage',
                     'verbose_name': 'メール送信管理',
                     'verbose_name_plural': 'メール送信管理'},
        ),
        migrations.RunPython(seed_mail_manage, reverse_code=noop),
    ]

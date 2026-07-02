import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('expenses', '0088_update_v_documentcontents_add_journal_fields'),
    ]

    operations = [
        migrations.CreateModel(
            name='T_AssetsSyncQueue',
            fields=[
                ('queue_id', models.AutoField(primary_key=True, serialize=False, verbose_name='キューID')),
                ('asset_no', models.CharField(max_length=13, verbose_name='資産NO')),
                ('operation', models.CharField(choices=[('insert', '新規登録'), ('update', '更新')], max_length=10, verbose_name='操作')),
                ('payload', models.JSONField(verbose_name='変更内容')),
                ('status', models.CharField(choices=[('pending', '未送信'), ('done', '送信済'), ('error', 'エラー')], default='pending', max_length=10, verbose_name='状態')),
                ('error_msg', models.CharField(blank=True, default='', max_length=500, verbose_name='エラー内容')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='登録日時')),
                ('processed_at', models.DateTimeField(blank=True, null=True, verbose_name='処理日時')),
                ('created_by', models.ForeignKey(db_column='created_by', on_delete=django.db.models.deletion.PROTECT, to_field='man_number', to='expenses.m_user', verbose_name='登録者')),
            ],
            options={
                'verbose_name': '固定資産同期キュー',
                'verbose_name_plural': '固定資産同期キュー',
                'db_table': 't_assets_sync_queue',
                'ordering': ['-created_at'],
            },
        ),
    ]

from django.db import migrations, models


def seed_mailcfg(apps, schema_editor):
    M_Item = apps.get_model('expenses', 'M_Item')
    entries = [
        ('approval', '1', '承認依頼・次ステップ通知'),
        ('result',   '1', '申請結果通知'),
        ('feedback', '1', 'フィードバック系通知'),
    ]
    for key, content, content2 in entries:
        M_Item.objects.get_or_create(
            data_kbn='MAILCFG',
            key=key,
            defaults={'content': content, 'content2': content2},
        )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [('expenses', '0063_update_v_documentcontents_add_applicant_fields')]

    operations = [
        # data_kbn / key を拡張して MAILCFG 等の長い値を許容
        migrations.AlterField(
            model_name='m_item',
            name='data_kbn',
            field=models.CharField(blank=True, max_length=10, verbose_name='データ区分'),
        ),
        migrations.AlterField(
            model_name='m_item',
            name='key',
            field=models.CharField(blank=True, max_length=20, verbose_name='キー'),
        ),
        migrations.RunPython(seed_mailcfg, reverse_code=noop),
    ]

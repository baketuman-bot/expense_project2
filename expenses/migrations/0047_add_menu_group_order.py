from django.db import migrations, models


def set_default_menu_groups(apps, schema_editor):
    M_DocumentType = apps.get_model('expenses', 'M_DocumentType')
    defaults = {
        1: ('支出伺い',              10),
        2: ('支出伺い',              11),
        4: ('交際費・会議費支出伺い', 20),
        5: ('国内出張旅費精算',       30),
    }
    for pk, (group, order) in defaults.items():
        M_DocumentType.objects.filter(pk=pk).update(menu_group=group, menu_order=order)


class Migration(migrations.Migration):

    dependencies = [
        ('expenses', '0046_fix_feedback_collation2'),
    ]

    operations = [
        migrations.AddField(
            model_name='m_documenttype',
            name='menu_group',
            field=models.CharField(
                blank=True,
                default='',
                help_text='サイドバーのグループ見出し。空欄の場合はサイドバーに表示されない',
                max_length=50,
                verbose_name='サイドバーグループ名',
            ),
        ),
        migrations.AddField(
            model_name='m_documenttype',
            name='menu_order',
            field=models.SmallIntegerField(
                default=0,
                help_text='サイドバーでの表示順（小さい値が先）',
                verbose_name='メニュー表示順',
            ),
        ),
        migrations.RunPython(set_default_menu_groups, migrations.RunPython.noop),
    ]

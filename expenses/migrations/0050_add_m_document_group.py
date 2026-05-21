from django.db import migrations, models


def populate_initial_data(apps, schema_editor):
    M_DocumentGroup = apps.get_model('expenses', 'M_DocumentGroup')
    M_DocumentType  = apps.get_model('expenses', 'M_DocumentType')
    M_Item          = apps.get_model('expenses', 'M_Item')

    # m_document_types の既存 menu_group を収集して初期レコードを生成
    seen = {}
    for dt in M_DocumentType.objects.exclude(menu_group='').order_by('menu_order'):
        if dt.menu_group not in seen:
            seen[dt.menu_group] = {'category': dt.category, 'menu_order': dt.menu_order}

    for group_key, info in seen.items():
        M_DocumentGroup.objects.get_or_create(
            menu_group=group_key,
            defaults={
                'menu_group_name': group_key,
                'category':        info['category'],
                'menu_order':      info['menu_order'],
            },
        )

    # マスタ設定メニューに追加（key は表示順ソート用の識別子）
    M_Item.objects.get_or_create(
        data_kbn='MST',
        key='DGR',
        defaults={'content': 'm_document_group', 'content2': '文書グループマスタ'},
    )


def remove_initial_data(apps, schema_editor):
    apps.get_model('expenses', 'M_Item').objects.filter(
        data_kbn='MST', key='DGR'
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('expenses', '0049_create_individual_views'),
    ]

    operations = [
        migrations.CreateModel(
            name='M_DocumentGroup',
            fields=[
                ('menu_group',      models.CharField('グループコード', max_length=50, primary_key=True, serialize=False)),
                ('menu_group_name', models.CharField('グループ名',     max_length=50)),
                ('category',        models.CharField(
                    'カテゴリ', max_length=20,
                    choices=[('expense', '費用精算'), ('assets', '固定資産')],
                    default='expense',
                )),
                ('menu_order',      models.SmallIntegerField('表示順', default=0)),
            ],
            options={
                'verbose_name':        '文書グループマスタ',
                'verbose_name_plural': '文書グループマスタ',
                'db_table':            'm_document_group',
                'ordering':            ['menu_order'],
            },
        ),
        migrations.RunPython(populate_initial_data, reverse_code=remove_initial_data),
    ]

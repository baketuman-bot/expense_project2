from django.db import migrations, models


def seed_mst_entry(apps, schema_editor):
    M_Item = apps.get_model('expenses', 'M_Item')
    M_Item.objects.get_or_create(
        data_kbn='MST',
        content='m_account_sub',
        defaults={'key': '17', 'content2': '補助科目'},
    )


def remove_mst_entry(apps, schema_editor):
    M_Item = apps.get_model('expenses', 'M_Item')
    M_Item.objects.filter(data_kbn='MST', content='m_account_sub').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('expenses', '0073_update_v_documentcontents_add_consumption_fields'),
    ]

    operations = [
        migrations.CreateModel(
            name='M_AccountSub',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('account_cd', models.CharField(max_length=20, verbose_name='勘定科目コード')),
                ('sub_account_cd', models.CharField(max_length=5, verbose_name='補助科目コード')),
                ('sub_account_name', models.CharField(max_length=50, verbose_name='補助科目名')),
            ],
            options={
                'verbose_name': '補助科目マスタ',
                'verbose_name_plural': '補助科目マスタ',
                'db_table': 'm_account_sub',
                'ordering': ['account_cd', 'sub_account_cd'],
            },
        ),
        migrations.AlterUniqueTogether(
            name='m_accountsub',
            unique_together={('account_cd', 'sub_account_cd')},
        ),
        migrations.RunPython(seed_mst_entry, remove_mst_entry),
    ]

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('expenses', '0082_rename_table_m_exchangerate'),
    ]

    operations = [
        migrations.AddField(
            model_name='m_accountsub',
            name='pr_kbn',
            field=models.SmallIntegerField(default=0, verbose_name='表示デフォルト区分'),
        ),
    ]

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('expenses', '0054_alter_T_ASSETS_nullable'),
    ]

    operations = [
        migrations.AddField(
            model_name='t_document',
            name='is_settled',
            field=models.BooleanField(default=False, verbose_name='精算完了', db_column='is_settled'),
        ),
        migrations.AddField(
            model_name='t_document',
            name='settled_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='精算日時', db_column='settled_at'),
        ),
    ]

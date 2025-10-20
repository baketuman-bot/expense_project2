from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('expenses', '0003_t_expensemain_memo'),
    ]

    operations = [
        migrations.AddField(
            model_name='t_expensedetail',
            name='tekikakusha_cd',
            field=models.CharField(
                verbose_name='登録番号',
                max_length=15,
                null=True,
                blank=True,
            ),
        ),
    ]

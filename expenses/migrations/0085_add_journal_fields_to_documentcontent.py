from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('expenses', '0084_add_mysql_comments'),
    ]

    operations = [
        # 借方フィールド
        migrations.AddField(
            model_name='t_documentcontent',
            name='journal_amont',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True, verbose_name='借方税抜金額'),
        ),
        migrations.AddField(
            model_name='t_documentcontent',
            name='journal_tax',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True, verbose_name='借方税額'),
        ),
        migrations.AddField(
            model_name='t_documentcontent',
            name='journal_amont_fx',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True, verbose_name='借方税抜外貨'),
        ),
        migrations.AddField(
            model_name='t_documentcontent',
            name='journal_tax_fx',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True, verbose_name='借方税額外貨'),
        ),
        migrations.AddField(
            model_name='t_documentcontent',
            name='journal_discription_deb',
            field=models.CharField(blank=True, max_length=50, null=True, verbose_name='借方適用'),
        ),
        # 貸方フィールド
        migrations.AddField(
            model_name='t_documentcontent',
            name='account_cd_cre',
            field=models.CharField(blank=True, max_length=20, null=True, verbose_name='貸方科目コード'),
        ),
        migrations.AddField(
            model_name='t_documentcontent',
            name='account_sub_cd_cre',
            field=models.CharField(blank=True, max_length=10, null=True, verbose_name='貸方補助科目コード'),
        ),
        migrations.AddField(
            model_name='t_documentcontent',
            name='journal_amount_cre',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True, verbose_name='貸方税抜金額'),
        ),
        migrations.AddField(
            model_name='t_documentcontent',
            name='journal_amont_fx_cre',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True, verbose_name='貸方税抜外貨'),
        ),
        migrations.AddField(
            model_name='t_documentcontent',
            name='journal_tori_cd_cre',
            field=models.CharField(blank=True, max_length=10, null=True, verbose_name='貸方取引先コード'),
        ),
        migrations.AddField(
            model_name='t_documentcontent',
            name='journal_discription_cre',
            field=models.CharField(blank=True, max_length=50, null=True, verbose_name='貸方摘要'),
        ),
    ]

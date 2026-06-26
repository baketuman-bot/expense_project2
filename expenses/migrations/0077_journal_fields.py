from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('expenses', '0076_add_assets_workflow_scope'),
    ]

    operations = [
        migrations.AddField(
            model_name='t_documentcontent',
            name='hojo_cd',
            field=models.CharField(blank=True, max_length=10, null=True, verbose_name='補助科目コード'),
        ),
        migrations.AddField(
            model_name='t_documentcontent',
            name='hojo_name',
            field=models.CharField(blank=True, max_length=100, null=True, verbose_name='補助科目名'),
        ),
        migrations.AddField(
            model_name='t_documentcontent',
            name='journal_tax_kbn',
            field=models.CharField(blank=True, max_length=10, null=True, verbose_name='仕訳税区分'),
        ),
        migrations.AddField(
            model_name='t_documentcontent',
            name='journal_tax_rate',
            field=models.CharField(blank=True, max_length=10, null=True, verbose_name='仕訳税率'),
        ),
        migrations.AddField(
            model_name='t_documentcontent',
            name='journal_fx_rate',
            field=models.CharField(blank=True, max_length=20, null=True, verbose_name='換算レート'),
        ),
        migrations.AddField(
            model_name='t_documentcontent',
            name='journal_fx_tax',
            field=models.CharField(blank=True, max_length=20, null=True, verbose_name='外貨税額'),
        ),
        migrations.AddField(
            model_name='t_documentcontent',
            name='journal_done',
            field=models.BooleanField(default=False, verbose_name='仕訳入力済'),
        ),
    ]

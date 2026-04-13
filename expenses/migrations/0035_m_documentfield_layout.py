from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('expenses', '0034_add_corpo_card_no'),
    ]

    operations = [
        migrations.AddField(
            model_name='m_documentfield',
            name='field_order',
            field=models.IntegerField('表示順', default=0),
        ),
        migrations.AddField(
            model_name='m_documentfield',
            name='col_width',
            field=models.IntegerField('幅(col-md-N 1〜12)', default=4),
        ),
        migrations.AddField(
            model_name='m_documentfield',
            name='row_break',
            field=models.BooleanField('この前で改行', default=False),
        ),
        migrations.AddField(
            model_name='m_documentfield',
            name='required',
            field=models.BooleanField('必須', default=False),
        ),
        migrations.AddField(
            model_name='m_documentfield',
            name='placeholder',
            field=models.CharField('プレースホルダー', blank=True, default='', max_length=100),
        ),
        migrations.AddField(
            model_name='m_documentfield',
            name='field_help_text',
            field=models.CharField('補助テキスト', blank=True, default='', max_length=200),
        ),
        migrations.AddField(
            model_name='m_documentfield',
            name='calc_formula',
            field=models.CharField('計算式(label型用)', blank=True, default='', max_length=200),
        ),
        migrations.AlterModelOptions(
            name='m_documentfield',
            options={
                'ordering': ['document_type', 'field_order', 'field_name'],
                'verbose_name': '文書フィールドマスタ',
                'verbose_name_plural': '文書フィールドマスタ',
            },
        ),
    ]

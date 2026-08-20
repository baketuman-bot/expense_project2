"""中国輸出Invoice管理: 加算調整率マスタのラベル整備と、貨物概要区分マスタの復旧。

0122 のシードは django_migrations 上「適用済み」と記録されているのに、本番DB
(expense_db) には CHN_CARGO / CHN_ADJRT の行が1件も残っていなかった。0122 の
逆方向が該当行を delete() する作りになっているため、巻き戻しで消えたまま
記録だけが残った可能性が高い。どちらも必須の選択肢なので、行が無いと報告
ウィザードの入力が完了できない。

このマイグレーションは冪等に整備し直す:

- CHN_ADJRT は update_or_create で、業務で使う正式なラベルに揃える
  （材料等 0% / 輸送費中国負担 1% / その他 5%）
- CHN_CARGO は get_or_create で、欠けている行だけを補う
  （運用側で手直ししたラベルを上書きしないため）

**逆方向はデータを消さない。** マスタを削除する巻き戻しは今回のような事故を
生むため行わない（プロジェクト規約でも破壊的マイグレーションは禁止）。
"""
from django.db import migrations

# key は表示順を兼ねた連番。content が画面に出るラベル、content2 が
# T_ChinaInvoice.adjustment_rate_value に入る数値（Decimal に変換される）。
ADJRATE_ROWS = [
    ('1', '材料等 0%', '0.00'),
    ('2', '輸送費中国負担 1%', '1.00'),
    ('3', 'その他 5%', '5.00'),
]

# content2='OTHER' の行は「その他」判定に使われ、選択時に補足入力が必須になる。
CARGO_ROWS = [
    ('1', '製品', ''),
    ('2', '資材', ''),
    ('3', '部品', ''),
    ('4', '金型', ''),
    ('5', '設備', ''),
    ('6', 'その他', 'OTHER'),
]


def repair_master_data(apps, schema_editor):
    M_Item = apps.get_model('expenses', 'M_Item')

    for order, (key, content, content2) in enumerate(ADJRATE_ROWS, start=1):
        M_Item.objects.update_or_create(
            data_kbn='CHN_ADJRT', key=key,
            defaults={'content': content, 'content2': content2, 'order_by': order},
        )

    for order, (key, content, content2) in enumerate(CARGO_ROWS, start=1):
        M_Item.objects.get_or_create(
            data_kbn='CHN_CARGO', key=key,
            defaults={'content': content, 'content2': content2, 'order_by': order},
        )


class Migration(migrations.Migration):

    dependencies = [
        ('expenses', '0122_china_invoice_master_seed'),
    ]

    operations = [
        # 逆方向は noop。マスタを消す巻き戻しは事故のもとなので行わない
        migrations.RunPython(repair_master_data, migrations.RunPython.noop),
    ]

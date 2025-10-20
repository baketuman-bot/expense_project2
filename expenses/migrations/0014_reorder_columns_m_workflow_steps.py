from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("expenses", "0013_alter_t_documentapprover_document_id_and_more"),
    ]

    operations = [
        migrations.RunSQL(
            sql=[
                # 1) workflow_template_id を先頭に
                "ALTER TABLE `m_workflow_steps` MODIFY COLUMN `workflow_template_id` int NOT NULL FIRST",
                # 2) step_id を workflow_template_id の後に（PK/AI 属性は維持）
                "ALTER TABLE `m_workflow_steps` MODIFY COLUMN `step_id` int NOT NULL AUTO_INCREMENT AFTER `workflow_template_id`",
                # 3) 以下、指定順に並べる
                "ALTER TABLE `m_workflow_steps` MODIFY COLUMN `step_order` int NOT NULL AFTER `step_id`",
                "ALTER TABLE `m_workflow_steps` MODIFY COLUMN `step_type` varchar(13) NOT NULL AFTER `step_order`",
                "ALTER TABLE `m_workflow_steps` MODIFY COLUMN `condition_expr` varchar(255) NULL AFTER `step_type`",
                "ALTER TABLE `m_workflow_steps` MODIFY COLUMN `approver_post_cd` varchar(15) NULL AFTER `condition_expr`",
                "ALTER TABLE `m_workflow_steps` MODIFY COLUMN `allowed_post_cd` varchar(15) NULL AFTER `approver_post_cd`",
                "ALTER TABLE `m_workflow_steps` MODIFY COLUMN `allowed_bumon_scope` varchar(7) NOT NULL AFTER `allowed_post_cd`",
                "ALTER TABLE `m_workflow_steps` MODIFY COLUMN `group_id` int NULL AFTER `allowed_bumon_scope`",
            ],
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]

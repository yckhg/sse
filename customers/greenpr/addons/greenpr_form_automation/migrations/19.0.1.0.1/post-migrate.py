"""Migration: parameterize mail_template_lead_inquiry.email_to via ir.config_parameter.

Prior to 19.0.1.0.1 the template hardcoded `greenpr9@gmail.com`. The XML data
file carries `noupdate="1"` so upgrades cannot rewrite the field — this script
forces the rewrite on upgrade to 19.0.1.0.1 so existing tenants pick up the
Jinja expression (with the same fallback value, so runtime behavior is
unchanged when `greenpr_form_automation.inquiry_recipient` is absent).
"""

NEW_EMAIL_TO = (
    "{{ (env['ir.config_parameter'].sudo()"
    ".get_param('greenpr_form_automation.inquiry_recipient')"
    " or 'greenpr9@gmail.com') }}"
)
OLD_EMAIL_TO = "greenpr9@gmail.com"


def migrate(cr, version):
    cr.execute(
        """
        SELECT res_id FROM ir_model_data
         WHERE module = 'greenpr_form_automation'
           AND name   = 'mail_template_lead_inquiry'
           AND model  = 'mail.template'
        """
    )
    row = cr.fetchone()
    if not row:
        return
    template_id = row[0]
    cr.execute(
        "UPDATE mail_template SET email_to = %s WHERE id = %s AND email_to = %s",
        (NEW_EMAIL_TO, template_id, OLD_EMAIL_TO),
    )

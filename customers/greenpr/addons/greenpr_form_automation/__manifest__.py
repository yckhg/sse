{
    'name': 'Greenpr Form Automation',
    'summary': 'Automate Lead + SMTP email on /contactus form submission',
    'description': (
        'Custom tenant module for greenpr. Defines a mail.template for '
        'quote inquiries and a base.automation rule that emails '
        'greenpr9@gmail.com automatically whenever a website-sourced '
        'crm.lead is created. No UI interaction required beyond keeping '
        'the /contactus form action set to "Create Opportunity".'
    ),
    'author': 'SSE',
    'website': 'https://greenpr.online',
    'category': 'Sales/CRM',
    'version': '19.0.1.0.0',
    'license': 'LGPL-3',
    'depends': ['crm', 'mail', 'website_crm'],
    'data': [],
    'installable': True,
    'application': False,
    'auto_install': False,
}

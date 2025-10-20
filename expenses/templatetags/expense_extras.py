from django import template
from django.template.defaultfilters import stringfilter

register = template.Library()

@register.filter
@stringfilter
def is_image(filename):
    """
    ファイル名から画像ファイルかどうかを判定するフィルター
    """
    ext = filename.lower()
    return ext.endswith(('.jpg', '.jpeg', '.png', '.gif'))

@register.filter
@stringfilter
def is_pdf(filename):
    """
    ファイル名からPDFファイルかどうかを判定するフィルター
    """
    return filename.lower().endswith('.pdf')
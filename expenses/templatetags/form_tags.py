from django import template
from django.forms.boundfield import BoundField

register = template.Library()

@register.filter(name='add_class')
def add_class(value, arg):
    if not isinstance(value, BoundField):
        return value
    
    css_classes = value.field.widget.attrs.get('class', '')
    if css_classes:
        css_classes = f"{css_classes} {arg}"
    else:
        css_classes = arg
    return value.as_widget(attrs={'class': css_classes})

@register.filter(name='attr')
def set_attr(value, arg):
    """
    任意の属性をウィジェットに付与するテンプレートフィルタ。
    例: {{ field|attr:"multiple:multiple" }} / {{ field|attr:"placeholder:入力してください" }}
    """
    if not isinstance(value, BoundField):
        return value
    if not isinstance(arg, str) or ':' not in arg:
        return value
    key, val = arg.split(':', 1)
    current = value.field.widget.attrs.copy()
    # class は追記、それ以外は上書き
    if key == 'class' and current.get('class') and val:
        merged_class = f"{current['class']} {val}"
        current['class'] = merged_class
    else:
        current[key] = val
    return value.as_widget(attrs=current)

@register.filter(name='is_image')
def is_image(file_field):
    """拡張子ベースで画像かどうかを判定する簡易フィルタ。"""
    try:
        name = getattr(file_field, 'name', '') or str(file_field)
        name = name.lower()
        return any(name.endswith(ext) for ext in ('.jpg', '.jpeg', '.png', '.gif', '.webp'))
    except Exception:
        return False

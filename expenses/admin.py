from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.http import HttpResponse
import csv
from .models import (
    M_User, M_Bumon, M_Post, M_Status, M_Account, M_Group, M_BelongTo, V_Group,
    T_Document, T_DocumentContent
)

@admin.register(M_Group)
class GroupAdmin(admin.ModelAdmin):
    list_display = ('group_cd', 'group_name', 'upper_group_cd')
    list_filter = ('upper_group_cd',)
    search_fields = ('group_cd', 'group_name', 'upper_group_cd')
    ordering = ('group_cd',)

@admin.register(M_BelongTo)
class BelongToAdmin(admin.ModelAdmin):
    list_display = ('man_number', 'get_user_name', 'group_cd', 'get_group_name', 'created_at')
    list_filter = ('group_cd', 'created_at')
    search_fields = ('man_number__man_number', 'man_number__user_name', 'group_cd__group_cd', 'group_cd__group_name')
    ordering = ('man_number', 'group_cd')
    date_hierarchy = 'created_at'

    def get_user_name(self, obj):
        return obj.man_number.user_name
    get_user_name.short_description = '氏名'
    get_user_name.admin_order_field = 'man_number__user_name'

    def get_group_name(self, obj):
        return obj.group_cd.group_name
    get_group_name.short_description = '部署名'
    get_group_name.admin_order_field = 'group_cd__group_name'

@admin.register(V_Group)
class GroupRelationAdmin(admin.ModelAdmin):
    list_display = ('group_cd', 'relation_group_cd')
    search_fields = ('group_cd', 'relation_group_cd')
    ordering = ('group_cd', 'relation_group_cd')

    def has_add_permission(self, request):
        return False  # 追加を禁止

    def has_change_permission(self, request, obj=None):
        return False  # 変更を禁止

    def has_delete_permission(self, request, obj=None):
        return False  # 削除を禁止

@admin.register(M_User)
class CustomUserAdmin(UserAdmin):
    list_display = ('username', 'man_number', 'user_name', 'email', 'bumon_cd', 'post_cd', 'role', 'is_staff')
    list_filter = ('is_staff', 'bumon_cd', 'post_cd', 'role')
    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        ('個人情報', {'fields': ('man_number', 'user_name', 'email', 'bumon_cd', 'post_cd', 'role')}),
        ('権限', {'fields': ('is_active', 'is_staff', 'is_superuser', 'user_permissions')}),
    )
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('username', 'password1', 'password2', 'man_number', 'user_name', 'email', 'bumon_cd', 'post_cd', 'role'),
        }),
    )
    search_fields = ('username', 'man_number', 'user_name', 'email')
    ordering = ('username',)
    filter_horizontal = ('user_permissions',)

class DocumentContentInline(admin.TabularInline):
    model = T_DocumentContent
    extra = 1
    fields = ("date", "amount", "purpose", "shiharaisaki", "account")


@admin.register(T_Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ('document_id', 'title', 'man_number', 'status_cd', 'created_at', 'total_amount')
    list_filter = ('status_cd', 'created_at', 'document_type')
    search_fields = ('document_id', 'title', 'man_number__username', 'man_number__user_name')
    ordering = ('-created_at',)
    date_hierarchy = 'created_at'
    inlines = [DocumentContentInline]





@admin.register(M_Bumon)
class BumonAdmin(admin.ModelAdmin):
    list_display = ('bumon_cd', 'bumon_name',)

@admin.register(M_Post)
class PostAdmin(admin.ModelAdmin):
    list_display = ('post_cd', 'post_name',)

@admin.register(M_Status)
class StatusAdmin(admin.ModelAdmin):
    list_display = ('status_cd', 'status_name',)

@admin.register(M_Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ('account_cd', 'account_name',)



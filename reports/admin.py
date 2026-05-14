from django.contrib import admin

from .models import Report, ReportRemark, ReportTemplate, TDSDocumentTemplate


@admin.register(ReportRemark)
class ReportRemarkAdmin(admin.ModelAdmin):
    list_display = ("title", "sort_order", "is_active")
    list_filter = ("is_active",)
    search_fields = ("title", "content")


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ("booking", "status", "final_outcome", "manager_name", "incharge_name", "analysis_end_date", "created_at")
    list_filter = ("status", "final_outcome")
    search_fields = ("booking__sample_reg_no", "manager_name", "incharge_name", "remark_text")


@admin.register(ReportTemplate)
class ReportTemplateAdmin(admin.ModelAdmin):
    list_display = ("name", "sample_name", "protocol", "is_active", "created_at")
    list_filter = ("is_active", "protocol")
    search_fields = ("name", "description", "content")


@admin.register(TDSDocumentTemplate)
class TDSDocumentTemplateAdmin(admin.ModelAdmin):
    list_display = ("name", "document_type", "test", "is_active", "updated_at")
    list_filter = ("document_type", "is_active", "test")
    search_fields = ("name", "description", "content", "test__name")

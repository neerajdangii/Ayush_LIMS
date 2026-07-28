from django.contrib import admin

from .models import (
    Booking,
    CustomerMaster,
    ManufacturerMaster,
    ProtocolMaster,
    SampleNameMaster,
    SubmitterMaster,
    TestMaster,
    UOMMaster,
)


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ("sample_reg_no", "booking_date", "customer", "sample_name", "booking_type", "status")
    list_filter = ("booking_type", "status", "sample_type")
    search_fields = ("sample_reg_no", "customer__name", "sample_name__name")


@admin.register(SubmitterMaster, ManufacturerMaster, SampleNameMaster, TestMaster, ProtocolMaster, UOMMaster)
class MasterAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name",)


@admin.register(CustomerMaster)
class CustomerMasterAdmin(admin.ModelAdmin):
    list_display = ("name", "contact_person", "telephone", "email", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name", "address", "contact_person", "telephone", "email")

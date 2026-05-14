from django import forms

from reports.models import ReportRemark

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

DATE_FORMAT_DMY = "%d/%m/%Y"
DATETIME_FORMAT_DMY = "%d/%m/%Y %I:%M %p"
DATE_INPUT_FORMAT = "%Y-%m-%d"
DATETIME_LOCAL_INPUT_FORMAT = "%Y-%m-%dT%H:%M"
DATE_PLACEHOLDER = "DD/MM/YYYY"
DATETIME_PLACEHOLDER = "DD/MM/YYYY HH:MM AM"


class CustomerSelect(forms.Select):
    def __init__(self, *args, address_map=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.address_map = address_map or {}

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex=subindex, attrs=attrs)
        option_value = option.get("value")
        if option_value is not None:
            address = self.address_map.get(str(option_value), "")
            if address:
                option["attrs"]["data-address"] = address
        return option


class SampleNameSelect(forms.Select):
    def __init__(self, *args, sample_map=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.sample_map = sample_map or {}

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex=subindex, attrs=attrs)
        option_value = option.get("value")
        sample_data = self.sample_map.get(str(option_value), {})
        for key, attr_name in (
            ("sample_type", "data-sample-type"),
            ("generic_name", "data-generic-name"),
            ("discipline", "data-discipline"),
            ("test_group", "data-test-group"),
        ):
            value = sample_data.get(key, "")
            if value:
                option["attrs"][attr_name] = value
        return option


class BookingForm(forms.ModelForm):
    DATETIME_INPUT_FIELDS = [
        "booking_date",
        "letter_date",
        "sampling_upto",
        "sample_receipt_date",
        "analysis_start_date",
        "analysis_end_date",
    ]
    DATE_INPUT_FIELDS = [
        "manufacture_date",
        "expiry_retest_date",
    ]

    class Meta:
        model = Booking
        fields = [
            "booking_date",
            "letter_date",
            "sampling_upto",
            "sample_receipt_date",
            "customer",
            "submitter",
            "manufacturer",
            "sample_name",
            "sample_type",
            "test_to_be_performed",
            "protocol",
            "uom",
            "booking_type",
            "sample_qty",
            "sample_location",
            "packaging_mode",
            "sample_condition",
            "batch_no",
            "batch_size",
            "manufacture_date",
            "expiry_retest_date",
            "license_no",
            "customer_sr_no",
            "collected_by_name",
            "sampling_procedure",
            "analysis_start_date",
            "analysis_end_date",
            "remarks",
        ]
        widgets = {
            "booking_date": forms.DateTimeInput(
                format=DATETIME_FORMAT_DMY,
                attrs={
                    "type": "text",
                    "class": "form-control booking-date-input",
                    "data-picker-kind": "datetime",
                    "step": "60",
                    "placeholder": DATETIME_PLACEHOLDER,
                    "autocomplete": "off",
                    "title": "",
                },
            ),
            "letter_date": forms.DateTimeInput(
                format=DATETIME_FORMAT_DMY,
                attrs={
                    "type": "text",
                    "class": "form-control booking-date-input",
                    "data-picker-kind": "datetime",
                    "step": "60",
                    "placeholder": DATETIME_PLACEHOLDER,
                    "autocomplete": "off",
                    "title": "",
                },
            ),
            "sampling_upto": forms.DateTimeInput(
                format=DATETIME_FORMAT_DMY,
                attrs={
                    "type": "text",
                    "class": "form-control booking-date-input",
                    "data-picker-kind": "datetime",
                    "step": "60",
                    "placeholder": DATETIME_PLACEHOLDER,
                    "autocomplete": "off",
                    "title": "",
                },
            ),
            "sample_receipt_date": forms.DateTimeInput(
                format=DATETIME_FORMAT_DMY,
                attrs={
                    "type": "text",
                    "class": "form-control booking-date-input",
                    "data-picker-kind": "datetime",
                    "step": "60",
                    "placeholder": DATETIME_PLACEHOLDER,
                    "autocomplete": "off",
                    "title": "",
                },
            ),
            "customer": forms.Select(attrs={"class": "form-select"}),
            "submitter": forms.Select(attrs={"class": "form-select"}),
            "manufacturer": forms.Select(attrs={"class": "form-select"}),
            "sample_name": forms.Select(attrs={"class": "form-select"}),
            "sample_type": forms.Select(attrs={"class": "form-select"}),
            "test_to_be_performed": forms.SelectMultiple(attrs={"class": "form-select", "size": 6}),
            "protocol": forms.Select(attrs={"class": "form-select"}),
            "uom": forms.Select(attrs={"class": "form-select"}),
            "booking_type": forms.Select(attrs={"class": "form-select"}),
            "sample_qty": forms.TextInput(attrs={"class": "form-control"}),
            "sample_location": forms.TextInput(attrs={"class": "form-control"}),
            "packaging_mode": forms.TextInput(attrs={"class": "form-control"}),
            "sample_condition": forms.TextInput(attrs={"class": "form-control"}),
            "batch_no": forms.TextInput(attrs={"class": "form-control"}),
            "batch_size": forms.TextInput(attrs={"class": "form-control"}),
            "manufacture_date": forms.DateInput(
                format=DATE_FORMAT_DMY,
                attrs={
                    "type": "text",
                    "class": "form-control booking-date-input",
                    "data-picker-kind": "date",
                    "placeholder": DATE_PLACEHOLDER,
                    "autocomplete": "off",
                    "title": "",
                },
            ),
            "expiry_retest_date": forms.DateInput(
                format=DATE_FORMAT_DMY,
                attrs={
                    "type": "text",
                    "class": "form-control booking-date-input",
                    "data-picker-kind": "date",
                    "placeholder": DATE_PLACEHOLDER,
                    "autocomplete": "off",
                    "title": "",
                },
            ),
            "license_no": forms.TextInput(attrs={"class": "form-control"}),
            "customer_sr_no": forms.TextInput(attrs={"class": "form-control"}),
            "collected_by_name": forms.TextInput(attrs={"class": "form-control"}),
            "sampling_procedure": forms.TextInput(attrs={"class": "form-control"}),
            "analysis_start_date": forms.DateTimeInput(
                format=DATETIME_FORMAT_DMY,
                attrs={
                    "type": "text",
                    "class": "form-control booking-date-input",
                    "data-picker-kind": "datetime",
                    "step": "60",
                    "placeholder": DATETIME_PLACEHOLDER,
                    "autocomplete": "off",
                    "title": "",
                },
            ),
            "analysis_end_date": forms.DateTimeInput(
                format=DATETIME_FORMAT_DMY,
                attrs={
                    "type": "text",
                    "class": "form-control booking-date-input",
                    "data-picker-kind": "datetime",
                    "step": "60",
                    "placeholder": DATETIME_PLACEHOLDER,
                    "autocomplete": "off",
                    "title": "",
                },
            ),
            "remarks": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        required_fields = [
            "booking_date",
            "customer",
            "submitter",
            "manufacturer",
            "sample_name",
            "sample_type",
            "test_to_be_performed",
            "protocol",
            "uom",
            "booking_type",
        ]
        for field_name in required_fields:
            self.fields[field_name].required = True
        for field_name in self.DATETIME_INPUT_FIELDS:
            self.fields[field_name].input_formats = [DATETIME_LOCAL_INPUT_FORMAT, DATETIME_FORMAT_DMY]
        for field_name in self.DATE_INPUT_FIELDS:
            self.fields[field_name].input_formats = [DATE_INPUT_FORMAT, DATE_FORMAT_DMY, DATETIME_FORMAT_DMY]

        self.fields["sample_type"].choices = [("", "Select sample type")] + list(Booking.SampleType.choices)
        self.fields["booking_type"].choices = [("", "Select booking type")] + list(Booking.BookingType.choices)
        customer_queryset = CustomerMaster.objects.order_by("-is_active", "name")
        self.fields["customer"].queryset = customer_queryset
        customer_widget = CustomerSelect(
            attrs={"class": "form-select"},
            address_map={str(customer.pk): customer.address for customer in customer_queryset},
        )
        customer_widget.choices = self.fields["customer"].choices
        self.fields["customer"].widget = customer_widget
        self.fields["submitter"].queryset = SubmitterMaster.objects.order_by("-is_active", "name")
        self.fields["manufacturer"].queryset = ManufacturerMaster.objects.order_by("-is_active", "name")
        sample_queryset = SampleNameMaster.objects.order_by("-is_active", "name")
        self.fields["sample_name"].queryset = sample_queryset
        sample_widget = SampleNameSelect(
            attrs={"class": "form-select"},
            sample_map={
                str(sample.pk): {
                    "sample_type": sample.sample_type,
                    "generic_name": sample.generic_name,
                    "discipline": sample.discipline,
                    "test_group": sample.test_group,
                }
                for sample in sample_queryset
            },
        )
        sample_widget.choices = self.fields["sample_name"].choices
        self.fields["sample_name"].widget = sample_widget
        self.fields["test_to_be_performed"].queryset = TestMaster.objects.order_by("-is_active", "name")
        self.fields["protocol"].queryset = ProtocolMaster.objects.order_by("-is_active", "name")
        self.fields["uom"].queryset = UOMMaster.objects.order_by("-is_active", "name")


class MasterForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "is_active" in self.fields and not self.instance.pk:
            self.fields["is_active"].initial = True

    class Meta:
        fields = ["name", "is_active"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }


class CustomerMasterForm(MasterForm):
    class Meta(MasterForm.Meta):
        model = CustomerMaster
        fields = ["name", "address", "is_active"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "address": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }


class SubmitterMasterForm(MasterForm):
    class Meta(MasterForm.Meta):
        model = SubmitterMaster


class ManufacturerMasterForm(MasterForm):
    class Meta(MasterForm.Meta):
        model = ManufacturerMaster


class SampleNameMasterForm(MasterForm):
    class Meta(MasterForm.Meta):
        model = SampleNameMaster
        fields = [
            "name",
            "generic_name",
            "sample_type",
            "discipline",
            "test_group",
            "method",
            "rate",
            "observationsheet_prefix",
            "customer",
            "description",
            "limits",
            "is_active",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "generic_name": forms.TextInput(attrs={"class": "form-control"}),
            "sample_type": forms.Select(attrs={"class": "form-select"}),
            "discipline": forms.Select(attrs={"class": "form-select"}),
            "test_group": forms.Select(attrs={"class": "form-select"}),
            "method": forms.TextInput(attrs={"class": "form-control"}),
            "rate": forms.TextInput(attrs={"class": "form-control"}),
            "observationsheet_prefix": forms.TextInput(attrs={"class": "form-control"}),
            "customer": forms.TextInput(attrs={"class": "form-control"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "limits": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }
        labels = {
            "generic_name": "Generic Name",
            "sample_type": "Sample Type",
            "test_group": "Test Group",
            "observationsheet_prefix": "Observationsheet Prefix",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["generic_name"].required = True
        self.fields["sample_type"].required = True
        self.fields["sample_type"].choices = [("", "--- Select Sample Type ---")] + list(
            SampleNameMaster.SampleType.choices
        )
        self.fields["discipline"].choices = [("", "--- Select Discipline ---")] + list(
            SampleNameMaster.Discipline.choices
        )
        self.fields["test_group"].choices = [("", "--- Select Test Group ---")] + list(
            SampleNameMaster.TestGroup.choices
        )


class TestMasterForm(MasterForm):
    class Meta(MasterForm.Meta):
        model = TestMaster


class ProtocolMasterForm(MasterForm):
    class Meta(MasterForm.Meta):
        model = ProtocolMaster


class UOMMasterForm(MasterForm):
    class Meta(MasterForm.Meta):
        model = UOMMaster


class ReportRemarkMasterForm(forms.ModelForm):
    class Meta:
        model = ReportRemark
        fields = ["title", "content", "sort_order", "is_active"]
        widgets = {
            "title": forms.TextInput(attrs={"class": "form-control"}),
            "content": forms.Textarea(attrs={"class": "form-control", "rows": 5}),
            "sort_order": forms.NumberInput(attrs={"class": "form-control"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

from html import escape
from pathlib import Path
import zipfile
import xml.etree.ElementTree as ET

from django import forms
from django.db.models import Q
from django.contrib.auth import get_user_model
from django.utils import timezone

from .models import Report, ReportRemark, ReportTemplate, TDSDocumentTemplate
from .template_library import build_generic_result_table, populate_main_table_rows

DATE_FORMAT_DMY = "%d/%m/%Y"
DATE_INPUT_FORMAT = "%Y-%m-%d"
DATE_PLACEHOLDER = "DD/MM/YYYY"

WORD_NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


def _extract_docx_printable_html(uploaded_file):
    uploaded_file.seek(0)
    with zipfile.ZipFile(uploaded_file) as docx:
        xml_content = docx.read("word/document.xml")
    root = ET.fromstring(xml_content)
    body = root.find("w:body", WORD_NS)
    if body is None:
        return ""

    blocks = []
    for child in body:
        tag_name = child.tag.rsplit("}", 1)[-1]
        if tag_name == "p":
            text = "".join(node.text or "" for node in child.findall(".//w:t", WORD_NS)).strip()
            if text:
                blocks.append(f"<p>{escape(text)}</p>")
        elif tag_name == "tbl":
            rows = []
            for row in child.findall(".//w:tr", WORD_NS):
                cells = []
                for cell in row.findall("./w:tc", WORD_NS):
                    cell_text = " ".join(
                        "".join(node.text or "" for node in para.findall(".//w:t", WORD_NS)).strip()
                        for para in cell.findall("./w:p", WORD_NS)
                    ).strip()
                    cells.append(f"<td>{escape(cell_text)}</td>")
                if cells:
                    rows.append(f"<tr>{''.join(cells)}</tr>")
            if rows:
                blocks.append(f"<table border=\"1\" cellspacing=\"0\" cellpadding=\"4\"><tbody>{''.join(rows)}</tbody></table>")
    return "\n".join(blocks)


def _extract_uploaded_printable_content(uploaded_file):
    if not uploaded_file:
        return ""
    suffix = Path(uploaded_file.name or "").suffix.lower()
    uploaded_file.seek(0)
    try:
        if suffix == ".docx":
            return _extract_docx_printable_html(uploaded_file)
        if suffix in {".html", ".htm"}:
            return uploaded_file.read().decode("utf-8", errors="ignore").strip()
        if suffix == ".txt":
            text = uploaded_file.read().decode("utf-8", errors="ignore").strip()
            return "\n".join(f"<p>{escape(line)}</p>" for line in text.splitlines() if line.strip())
    finally:
        uploaded_file.seek(0)
    return ""


def _local_date(value):
    if not value:
        return None
    if hasattr(value, "tzinfo") and timezone.is_aware(value):
        value = timezone.localtime(value)
    return value.date() if hasattr(value, "date") else value


class ReportApprovalForm(forms.ModelForm):
    incharge_user = forms.ModelChoiceField(
        queryset=get_user_model().objects.none(),
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
        label="Person In-charge",
    )
    analysis_start_date = forms.DateField(
        required=False,
        widget=forms.DateInput(
            format=DATE_FORMAT_DMY,
            attrs={
                "type": "text",
                "class": "form-control booking-date-input",
                "placeholder": DATE_PLACEHOLDER,
                "data-picker-kind": "date",
                "data-close-on-pick": "1",
                "autocomplete": "off",
                "title": "",
            },
        ),
    )
    analysis_end_date = forms.DateField(
        required=False,
        widget=forms.DateInput(
            format=DATE_FORMAT_DMY,
            attrs={
                "type": "text",
                "class": "form-control booking-date-input",
                "placeholder": DATE_PLACEHOLDER,
                "data-picker-kind": "date",
                "data-close-on-pick": "1",
                "autocomplete": "off",
                "title": "",
            },
        ),
    )

    class Meta:
        model = Report
        fields = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        UserModel = get_user_model()
        incharge_qs = (
            UserModel.objects.filter(is_active=True, groups__name="Incharge")
            .order_by("first_name", "last_name", "username")
            .distinct()
        )
        self.fields["incharge_user"].queryset = incharge_qs
        self.fields["analysis_start_date"].input_formats = [DATE_INPUT_FORMAT, DATE_FORMAT_DMY]
        self.fields["analysis_end_date"].input_formats = [DATE_INPUT_FORMAT, DATE_FORMAT_DMY]
        if self.instance and self.instance.pk and self.instance.booking_id:
            self.fields["analysis_start_date"].initial = _local_date(self.instance.booking.analysis_start_date)
            self.fields["analysis_end_date"].initial = _local_date(self.instance.booking.analysis_end_date)
            if self.instance.incharge_id:
                self.fields["incharge_user"].initial = self.instance.incharge_id
            else:
                default_incharge = incharge_qs.first()
                if default_incharge:
                    self.fields["incharge_user"].initial = default_incharge.pk


class COAEditForm(forms.ModelForm):
    selected_remarks = forms.ModelMultipleChoiceField(
        queryset=ReportRemark.objects.none(),
        required=False,
        widget=forms.SelectMultiple(attrs={"class": "d-none", "id": "id_selected_remarks", "size": 4}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        active_remarks = ReportRemark.objects.filter(is_active=True)
        self.fields["selected_remark"].queryset = active_remarks
        self.fields["selected_remarks"].queryset = active_remarks
        if self.instance and self.instance.selected_remark_id:
            self.initial["selected_remarks"] = [self.instance.selected_remark_id]
        current_template_id = self.instance.report_template_id if self.instance else None
        self.fields["report_template"].queryset = ReportTemplate.objects.filter(
            Q(is_active=True) | Q(pk=current_template_id)
        ).select_related("sample_name", "protocol")

        selected_template = self.instance.report_template if self.instance and self.instance.report_template_id else None
        if not selected_template:
            selected_template = self._suggest_template()
        if selected_template:
            self.initial["report_template"] = selected_template.pk
            self.fields["report_template"].initial = selected_template.pk

        existing_content = (self.instance.ceo_content or "") if self.instance else ""
        if existing_content:
            self.initial["ceo_content"] = existing_content
            self.fields["ceo_content"].initial = existing_content
        else:
            default_content = self._build_default_content(selected_template)
            self.initial["ceo_content"] = default_content
            self.fields["ceo_content"].initial = default_content

    def _selected_tests(self):
        if not self.instance or not getattr(self.instance, "booking", None):
            return []
        return list(
            self.instance.booking.test_to_be_performed.select_related("report_template").order_by("name")
        )

    def _has_assay_test(self, tests=None):
        selected_tests = tests if tests is not None else self._selected_tests()
        return any((test.name or "").strip().lower() == "assay" for test in selected_tests)

    def _build_default_content(self, selected_template=None):
        tests = self._selected_tests()
        selected_test_names = []
        template_html_blocks = []
        seen_template_ids = set()
        has_assay_test = self._has_assay_test(tests)

        for test in tests:
            if (test.name or "").strip():
                selected_test_names.append(test.name.strip())

            template = getattr(test, "report_template", None)
            if (
                has_assay_test
                and (test.name or "").strip().lower() == "assay"
                and template
                and template.is_active
                and template.content.strip()
            ):
                if template.pk not in seen_template_ids:
                    template_html_blocks.append(template.content.strip())
                    seen_template_ids.add(template.pk)

        content_blocks = []
        if (
            selected_template
            and selected_template.is_active
            and selected_template.content.strip()
        ):
            if selected_template.pk not in seen_template_ids:
                populated_template = populate_main_table_rows(
                    selected_template.content.strip(),
                    selected_test_names,
                )
                content_blocks.append(populated_template)
                seen_template_ids.add(selected_template.pk)

        content_blocks.extend(template_html_blocks)

        if not content_blocks:
            return build_generic_result_table(selected_test_names)

        return "\n<p>&nbsp;</p>\n".join(content_blocks)

    def _suggest_template(self):
        if not self.instance or not getattr(self.instance, "booking", None):
            return None

        booking = self.instance.booking
        queryset = ReportTemplate.objects.filter(is_active=True)
        default_template = queryset.filter(is_default=True).first()

        if default_template:
            return default_template

        tests = self._selected_tests()
        if not self._has_assay_test(tests):
            return None

        test_template = (
            booking.test_to_be_performed.filter(report_template__is_active=True)
            .select_related("report_template")
            .order_by("name")
            .first()
        )
        if test_template and test_template.report_template_id:
            return test_template.report_template

        if booking.sample_name_id and booking.protocol_id:
            exact = queryset.filter(sample_name_id=booking.sample_name_id, protocol_id=booking.protocol_id).first()
            if exact:
                return exact
        if booking.sample_name_id:
            by_sample = queryset.filter(sample_name_id=booking.sample_name_id, protocol__isnull=True).first()
            if by_sample:
                return by_sample
        if booking.protocol_id:
            by_protocol = queryset.filter(sample_name__isnull=True, protocol_id=booking.protocol_id).first()
            if by_protocol:
                return by_protocol
        return default_template or queryset.filter(sample_name__isnull=True, protocol__isnull=True).first()

    def clean(self):
        cleaned_data = super().clean()
        selected_remarks = list(cleaned_data.get("selected_remarks") or [])
        remark_text = (cleaned_data.get("remark_text") or "").strip()

        if selected_remarks:
            cleaned_data["selected_remark"] = selected_remarks[0]
        else:
            cleaned_data["selected_remark"] = None

        if selected_remarks and not remark_text:
            cleaned_data["remark_text"] = "\n".join(
                content for content in [remark.content.strip() for remark in selected_remarks] if content
            )

        return cleaned_data

    def clean_ceo_content(self):
        return (self.cleaned_data.get("ceo_content") or "").strip()

    class Meta:
        model = Report
        fields = ["report_template", "ceo_content", "final_outcome", "selected_remarks", "selected_remark", "remark_text"]
        widgets = {
            "report_template": forms.Select(attrs={"class": "form-select", "id": "id_report_template"}),
            "ceo_content": forms.Textarea(
                attrs={
                    "class": "form-control tinymce-editor",
                    "id": "editor",
                    "rows": 16,
                    "data-editor": "tinymce",
                }
            ),
            "final_outcome": forms.Select(attrs={"class": "form-select"}),
            "selected_remark": forms.HiddenInput(),
            "remark_text": forms.Textarea(attrs={"class": "form-control", "rows": 4}),
        }
        labels = {
            "report_template": "Report Template",
            "ceo_content": "CEO Content",
            "final_outcome": "Final Outcome",
            "selected_remarks": "Remark Master",
            "remark_text": "Remarks",
        }


class ReportTemplateForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get("is_default"):
            cleaned_data["is_active"] = True
        
        # Validate that content is not empty (only on new templates)
        content = cleaned_data.get("content", "").strip()
        if not self.instance.pk and (not content or content == ""):
            raise forms.ValidationError("Template content cannot be empty. Please add content to your template.")
        
        return cleaned_data

    class Meta:
        model = ReportTemplate
        fields = ["name", "description", "content", "is_active", "is_default"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "description": forms.TextInput(attrs={"class": "form-control"}),
            "content": forms.Textarea(
                attrs={
                    "class": "form-control tinymce-editor",
                    "rows": 18,
                    "data-editor": "tinymce",
                }
            ),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "is_default": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def clean_content(self):
        content = self.cleaned_data.get("content") or ""
        return content.strip() if isinstance(content, str) else content


class TDSDocumentTemplateForm(forms.ModelForm):
    class Meta:
        model = TDSDocumentTemplate
        fields = ["document_type", "name", "test", "description", "content", "source_file", "is_active"]
        widgets = {
            "document_type": forms.Select(attrs={"class": "form-select"}),
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "test": forms.Select(attrs={"class": "form-select"}),
            "description": forms.TextInput(attrs={"class": "form-control"}),
            "content": forms.Textarea(
                attrs={
                    "class": "form-control tinymce-editor",
                    "rows": 18,
                    "data-editor": "tinymce",
                }
            ),
            "source_file": forms.ClearableFileInput(attrs={"class": "form-control", "accept": ".doc,.docx,.pdf,.html,.htm,.txt"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }
        labels = {
            "test": "Test link for ADS",
            "content": "Printable Content",
            "source_file": "Word/PDF Source File",
        }

    def clean(self):
        cleaned_data = super().clean()
        document_type = cleaned_data.get("document_type")
        test = cleaned_data.get("test")
        content = (cleaned_data.get("content") or "").strip()
        source_file = cleaned_data.get("source_file") or getattr(self.instance, "source_file", None)
        uploaded_file = cleaned_data.get("source_file")

        if document_type == TDSDocumentTemplate.DocumentType.ADS and not test:
            raise forms.ValidationError("ADS templates should be linked with a test.")
        if not content and uploaded_file:
            content = _extract_uploaded_printable_content(uploaded_file)
            if not content:
                raise forms.ValidationError(
                    "Could not read printable content from this file. Upload a .docx, .html, or .txt file, or paste content manually."
                )
        if not content and not source_file:
            raise forms.ValidationError("Add printable content or upload a source file.")
        cleaned_data["content"] = content
        return cleaned_data

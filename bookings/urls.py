from django.urls import path

from .views import (
    BookingApproveView,
    BookingCreateView,
    BookingDeleteView,
    BookingDetailView,
    BookingListView,
    BookingUpdateView,
    DataSheetView,
    GetSimilarBookingDataView,
    InlineMasterCreateView,
    MasterCreateView,
    MasterDeleteView,
    MasterListView,
    MasterUpdateView,
    PartyPendingExcelView,
    PartyPendingPrintView,
)

app_name = "bookings"

urlpatterns = [
    path("", BookingListView.as_view(), name="list"),
    path("new/", BookingCreateView.as_view(), name="create"),
    path("data-sheet/", DataSheetView.as_view(), name="data_sheet"),
    path("view/<int:pk>/", BookingDetailView.as_view(), name="detail"),
    path("<int:pk>/edit/", BookingUpdateView.as_view(), name="edit"),
    path("<int:pk>/delete/", BookingDeleteView.as_view(), name="delete"),
    path("<int:pk>/approve/", BookingApproveView.as_view(), name="approve"),
    path("api/similar-booking-data/", GetSimilarBookingDataView.as_view(), name="api_similar_booking_data"),
    path("party-pending/excel/", PartyPendingExcelView.as_view(), name="party_pending_excel"),
    path("party-pending/print/", PartyPendingPrintView.as_view(), name="party_pending_print"),
    path("masters/<slug:slug>/", MasterListView.as_view(), name="master_list"),
    path("masters/<slug:slug>/add/", MasterCreateView.as_view(), name="master_add"),
    path("masters/<slug:slug>/<int:pk>/edit/", MasterUpdateView.as_view(), name="master_edit"),
    path("masters/<slug:slug>/<int:pk>/delete/", MasterDeleteView.as_view(), name="master_delete"),
    path("masters/<slug:slug>/inline-create/", InlineMasterCreateView.as_view(), name="master_inline_create"),
]

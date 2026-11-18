from django.urls import path

from crm.views import companies, manager_schedule, patch_meeting, post_call, post_meeting

urlpatterns = [
    path("companies", companies, name="company-list-create"),
    path("calls", post_call, name="call-create"),
    path("meetings", post_meeting, name="meeting-create"),
    path("meetings/<int:meeting_id>", patch_meeting, name="meeting-update"),
    path("managers/<int:manager_id>/schedule", manager_schedule, name="manager-schedule"),
]

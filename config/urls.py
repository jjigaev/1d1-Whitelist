from django.urls import path

from crm.views import patch_meeting, post_meeting

urlpatterns = [
    path("meetings", post_meeting, name="meeting-create"),
    path("meetings/<int:meeting_id>", patch_meeting, name="meeting-update"),
]

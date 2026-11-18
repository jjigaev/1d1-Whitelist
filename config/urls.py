from django.urls import path

from crm.views import post_meeting

urlpatterns = [
    path("meetings", post_meeting, name="meeting-create"),
]

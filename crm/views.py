from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .serializers import MeetingSerializer, MeetingUpdateSerializer
from .services import create_meeting, update_meeting


@api_view(["POST"])
def post_meeting(request):
    serializer = MeetingSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    meeting = create_meeting(**serializer.validated_data)
    return Response(MeetingSerializer(meeting).data, status=status.HTTP_201_CREATED)


@api_view(["PATCH"])
def patch_meeting(request, meeting_id):
    serializer = MeetingUpdateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    meeting = update_meeting(meeting_id=meeting_id, **serializer.validated_data)
    return Response(MeetingSerializer(meeting).data)

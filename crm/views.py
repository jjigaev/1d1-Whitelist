from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .serializers import MeetingSerializer
from .services import create_meeting


@api_view(["POST"])
def post_meeting(request):
    serializer = MeetingSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    meeting = create_meeting(**serializer.validated_data)
    return Response(MeetingSerializer(meeting).data, status=status.HTTP_201_CREATED)

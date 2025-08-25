# pagination.py
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.response import Response

class MessagesPaginator(LimitOffsetPagination):
    default_limit = 30
    max_limit = 100

    def get_paginated_response(self, messages_data, session_payload):
        return Response({
            "session": session_payload,
            "messages": messages_data,
            "pagination": {
                "count": self.count,
                "limit": self.get_limit(self.request),
                "offset": self.get_offset(self.request),
                "next": self.get_next_link(),
                "previous": self.get_previous_link(),
            }
        })
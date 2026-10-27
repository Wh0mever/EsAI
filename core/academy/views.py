from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from . import public

READ_RATE = "600/min"


class AcademyReadThrottle(AnonRateThrottle):
    """Свой счётчик вместо общего анонимного (30 в минуту).

    Страницу /academy собирает сервер Next, и весь SSR приходит в core с одного
    адреса: общий лимит отдал бы краулерам 429 и пустой каталог. Ответ
    маленький, из кэша, только чтение — лимит щедрый. Переопределить можно
    ставкой academy_read в DEFAULT_THROTTLE_RATES.
    """

    scope = "academy_read"

    def get_rate(self):
        return self.THROTTLE_RATES.get(self.scope) or READ_RATE


class CoursesView(APIView):
    """GET courses/ — {count, page_size, results, suggest_url, suggest}: все курсы сайта разом.

    Открыто всем. Параметров нет: страницы по page_size режет Next.
    """

    authentication_classes = []
    permission_classes = []
    throttle_classes = [AcademyReadThrottle]

    def get(self, request):
        response = Response(public.public_payload())
        response["Cache-Control"] = f"public, max-age={public.CACHE_S}"
        return response

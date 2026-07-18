from rest_framework.pagination import PageNumberPagination


class YekiPageNumberPagination(PageNumberPagination):
    """
    Pagination standard de l'API YÉKI (CDC_BACKEND §2.5).

    page_size=20 par défaut, ajustable par le client via ?page_size=,
    plafonné à 100 pour empêcher un client de réclamer une liste entière
    en une seule requête.
    """

    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class PaginatedListMixin:
    """
    Ajoute `paginate_queryset()`/`get_paginated_response()` à une `APIView`
    brute, sans passer par `generics.ListAPIView` (aucune vue de liste du
    projet n'en hérite — voir docs/API_FOUNDATIONS.md). Reproduit exactement
    le mécanisme de `generics.GenericAPIView` :

        class MaVue(PaginatedListMixin, APIView):
            def get(self, request):
                qs = MonModele.objects.all()
                page = self.paginate_queryset(qs)
                serializer = MonSerializer(page, many=True)
                return self.get_paginated_response(serializer.data)
    """

    pagination_class = YekiPageNumberPagination

    @property
    def paginator(self):
        if not hasattr(self, "_paginator"):
            self._paginator = self.pagination_class()
        return self._paginator

    def paginate_queryset(self, queryset):
        return self.paginator.paginate_queryset(queryset, self.request, view=self)

    def get_paginated_response(self, data):
        return self.paginator.get_paginated_response(data)

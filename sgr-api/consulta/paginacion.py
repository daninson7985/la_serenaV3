from rest_framework.pagination import PageNumberPagination


class Paginacion(PageNumberPagination):
    """50 resultados por página; ``?page_size=`` hasta 500."""
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 500

from django.contrib import admin
from .models import GoPayInvoice, GoPayWebhookEvent, Payment


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'created_at', 'user', 'provider', 'amount', 'currency', 'success', 'order_id'
    )
    list_filter = ('provider', 'success', 'currency', 'created_at')
    search_fields = ('order_id', 'user__email')
    readonly_fields = ('created_at',)
    date_hierarchy = 'created_at'
    ordering = ('-created_at', '-id')
    list_per_page = 50


class _ReadOnlyAdmin(admin.ModelAdmin):
    """Только просмотр: состояние счёта меняет код оплаты под блокировкой строки.

    Правка руками из этой админки обошла бы и блокировку, и сверку сумм.
    """

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(GoPayInvoice)
class GoPayInvoiceAdmin(_ReadOnlyAdmin):
    list_display = ('id', 'created_at', 'payment', 'env', 'status', 'amount', 'expires_at')
    list_filter = ('env', 'status')
    search_fields = ('provider_payment_id', 'payment__order_id')
    list_select_related = ('payment',)
    ordering = ('-created_at', '-id')
    list_per_page = 50


@admin.register(GoPayWebhookEvent)
class GoPayWebhookEventAdmin(_ReadOnlyAdmin):
    list_display = ('received_at', 'event', 'order_id', 'status', 'processed', 'result')
    list_filter = ('event', 'processed')
    search_fields = ('order_id', 'provider_payment_id')
    ordering = ('-received_at', '-id')
    list_per_page = 50

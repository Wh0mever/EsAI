from django.contrib import admin
from .models import Payment


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

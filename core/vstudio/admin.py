"""Админка видеостудии.

Главное здесь — дубли (Take): по ним разбирают «списали, а видео нет» и
«видео не пришло». Правила:
- дубль и запрос только для просмотра. Статус и деньги двигает конвейер
  условными UPDATE; сохранение формы записало бы строку, прочитанную в начале
  запроса, поверх свежей — и вернуло бы, например, charged в reserved;
- удалить открытый дубль нельзя: у него деньги в резерве и его ведёт воркер;
- у потерянных (lost) — действие «Довезти»: повторный опрос и выдача без
  списания (vstudio.pipeline.admin_redeliver);
- журнал генераций живёт в /admin-new/generations — туда ведёт ссылка
  с поиском по uid дубля (журнал хранит его в params.take);
- витрину первого экрана ведут в /admin-new/vstudio-showcase: там правки
  попадают в журнал действий. Здесь она — запасной вход, правки остаются
  только в истории объекта. И только здесь видно, собралась ли лёгкая копия
  ролика, и есть действие «Пересобрать».
"""
from __future__ import annotations

import json
import logging

from django import forms
from django.contrib import admin, messages
from django.db import transaction
from django.db.models import Count
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html
from django.utils.http import urlencode

from . import showcase
from .models import Asset, Project, ShowcaseItem, Shot, ShotInput, Take

logger = logging.getLogger("vstudio")

# Журнал генераций — страница admin-new (Next.js на том же домене).
GENERATIONS_URL = "/admin-new/generations"


def journal_url(take_uid: str) -> str:
    return f"{GENERATIONS_URL}?{urlencode({'q': take_uid})}"


def _pre(value):
    """JSON и длинный текст целиком, с переносами — без обрезки (правило студии)."""
    if value in (None, "", [], {}):
        return "—"
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2,
                                                          default=str)
    return format_html('<pre style="white-space:pre-wrap;word-break:break-word;'
                       'max-width:960px;margin:0">{}</pre>', text)


def _media_preview(url: str, height: int = 44):
    if not url:
        return "—"
    return format_html('<img src="{}" style="height:{}px;border-radius:6px" alt="" />', url, height)


class PartialSaveMixin:
    """Сохранять только поля, которые правили в форме.

    obj.save() записал бы все поля объекта целиком и мог бы вернуть назад то,
    что за эти миллисекунды поменял воркер (статус ассета, активность проекта).
    """

    def save_model(self, request, obj, form, change):
        if not change:
            return super().save_model(request, obj, form, change)
        fields = list(form.changed_data)
        if not fields:
            return None
        fields += [f.name for f in obj._meta.concrete_fields
                   if getattr(f, "auto_now", False) and f.name not in fields]
        obj.save(update_fields=fields)
        return None


# ---------------------------------------------------------------- проекты

@admin.register(Project)
class ProjectAdmin(PartialSaveMixin, admin.ModelAdmin):
    list_display = ("short_uid", "title_or_dash", "user", "kind", "shots_count", "is_archived",
                    "last_activity_at", "created_at")
    list_filter = ("kind", "is_archived", "last_activity_at")
    search_fields = ("uid", "title", "user__email")
    list_select_related = ("user",)
    ordering = ("-last_activity_at",)
    fields = ("uid", "user", "kind", "title", "is_archived", "settings_pretty",
              "last_activity_at", "created_at", "updated_at")
    # Правятся только название и архив: остальное ведёт сама студия.
    readonly_fields = ("uid", "user", "kind", "settings_pretty", "last_activity_at",
                       "created_at", "updated_at")

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_shots=Count("shots"))

    def has_add_permission(self, request):
        return False

    @admin.display(description="uid", ordering="uid")
    def short_uid(self, obj):
        return obj.uid[:8]

    @admin.display(description="Название", ordering="title")
    def title_or_dash(self, obj):
        return obj.title or "—"

    @admin.display(description="Запросов", ordering="_shots")
    def shots_count(self, obj):
        return getattr(obj, "_shots", None)

    @admin.display(description="Параметры панели")
    def settings_pretty(self, obj):
        return _pre(obj.settings)


# ---------------------------------------------------------------- материалы

class DeletedFilter(admin.SimpleListFilter):
    title = "удалён"
    parameter_name = "deleted"

    def lookups(self, request, model_admin):
        return (("0", "Нет"), ("1", "Да"))

    def queryset(self, request, queryset):
        if self.value() == "0":
            return queryset.filter(deleted_at__isnull=True)
        if self.value() == "1":
            return queryset.filter(deleted_at__isnull=False)
        return queryset


@admin.register(Asset)
class AssetAdmin(PartialSaveMixin, admin.ModelAdmin):
    list_display = ("preview", "short_uid", "user", "kind", "source", "status", "size",
                    "is_deleted", "created_at")
    list_filter = ("kind", "source", "status", DeletedFilter, "created_at")
    search_fields = ("uid", "sha256", "label", "user__email")
    list_select_related = ("user",)
    ordering = ("-created_at",)
    actions = ("soft_delete", "restore")
    fields = ("preview_large", "uid", "user", "project", "kind", "source", "status", "label",
              "file_link", "thumb", "mime", "bytes", "width", "height", "duration_s", "sha256",
              "flags_pretty", "meta_pretty", "origin_take", "error_code", "created_at", "deleted_at")
    # Правится только алиас: файл, размеры и состояние пишет конвейер.
    readonly_fields = ("preview_large", "uid", "user", "project", "kind", "source", "status",
                       "file_link", "thumb", "mime", "bytes", "width", "height", "duration_s",
                       "sha256", "flags_pretty", "meta_pretty", "origin_take", "error_code",
                       "created_at", "deleted_at")

    def has_add_permission(self, request):
        return False

    @admin.display(description="uid", ordering="uid")
    def short_uid(self, obj):
        return obj.uid[:8]

    @admin.display(description="Вид")
    def preview(self, obj):
        return _media_preview(obj.thumb_url or (obj.url if obj.kind == Asset.KIND_IMAGE else ""))

    @admin.display(description="Вид")
    def preview_large(self, obj):
        return _media_preview(obj.thumb_url or (obj.url if obj.kind == Asset.KIND_IMAGE else ""),
                              height=240)

    @admin.display(description="Размер")
    def size(self, obj):
        return f"{obj.width}×{obj.height}" if obj.width and obj.height else "—"

    @admin.display(description="Удалён", boolean=True, ordering="deleted_at")
    def is_deleted(self, obj):
        return obj.deleted_at is not None

    @admin.display(description="Файл")
    def file_link(self, obj):
        if not obj.file:
            return "—"
        return format_html('<a href="{}" target="_blank" rel="noopener">{}</a>', obj.url, obj.file)

    @admin.display(description="Отметки")
    def flags_pretty(self, obj):
        return _pre(obj.flags)

    @admin.display(description="Сведения")
    def meta_pretty(self, obj):
        return _pre(obj.meta)

    @admin.action(description="Удалить мягко (исчезнет у человека, файл сотрёт чистка через 30 дней)")
    def soft_delete(self, request, queryset):
        # Номера — до правки: при «выбрать все» список задан фильтром страницы,
        # и после неё те же строки под него уже не попадут.
        pks = list(queryset.filter(deleted_at__isnull=True).values_list("pk", flat=True))
        n = (Asset.objects.filter(pk__in=pks, deleted_at__isnull=True)
             .update(deleted_at=timezone.now()))
        # Удалённый результат пропадает и из витрины — сразу, а не когда истечёт её кэш.
        showcase.forget_assets(pks)
        self.message_user(request, f"Удалено мягко: {n}.", messages.SUCCESS)

    @admin.action(description="Восстановить удалённые")
    def restore(self, request, queryset):
        pks = list(queryset.filter(deleted_at__isnull=False).values_list("pk", flat=True))
        n = Asset.objects.filter(pk__in=pks, deleted_at__isnull=False).update(deleted_at=None)
        showcase.revive_assets(pks)
        self.message_user(request, f"Восстановлено: {n}.", messages.SUCCESS)


# ---------------------------------------------------------------- запросы

class ShotInputInline(admin.TabularInline):
    model = ShotInput
    extra = 0
    can_delete = False
    fields = ("slot", "position", "asset", "asset_preview", "role", "included")
    readonly_fields = fields
    ordering = ("slot", "position")

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    @admin.display(description="Вид")
    def asset_preview(self, obj):
        return _media_preview(obj.asset.thumb_url or obj.asset.url)


class TakeInline(admin.TabularInline):
    model = Take
    extra = 0
    can_delete = False
    fields = ("take_link", "status", "charge_state", "credits_reserved", "credits_charged",
              "error_code", "created_at", "finished_at")
    readonly_fields = fields
    ordering = ("created_at",)

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    @admin.display(description="Дубль")
    def take_link(self, obj):
        url = reverse("admin:vstudio_take_change", args=[obj.pk])
        return format_html('<a href="{}">{}</a>', url, obj.uid[:8])


@admin.register(Shot)
class ShotAdmin(admin.ModelAdmin):
    list_display = ("short_uid", "user", "project", "kind", "origin", "model_ref",
                    "prompt_short", "created_at")
    list_filter = ("kind", "origin", "model_ref", "created_at")
    search_fields = ("uid", "prompt_text", "user__email", "project__uid")
    list_select_related = ("user", "project")
    ordering = ("-created_at",)
    inlines = (ShotInputInline, TakeInline)
    fields = ("uid", "user", "project", "kind", "origin", "model", "model_ref", "forked_from",
              "prompt_pretty", "prompt_doc_pretty", "params_pretty", "created_at")
    readonly_fields = fields

    # Запрос после создания не меняется (§2.1) — только просмотр.
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    @admin.display(description="uid", ordering="uid")
    def short_uid(self, obj):
        return obj.uid[:8]

    @admin.display(description="Промпт")
    def prompt_short(self, obj):
        text = obj.prompt_text or ""
        return text if len(text) <= 80 else f"{text[:80]}… ({len(text)} симв.)"

    @admin.display(description="Промпт целиком")
    def prompt_pretty(self, obj):
        return _pre(obj.prompt_text)

    @admin.display(description="Промпт (документ)")
    def prompt_doc_pretty(self, obj):
        return _pre(obj.prompt_doc)

    @admin.display(description="Параметры")
    def params_pretty(self, obj):
        return _pre(obj.params)


# ---------------------------------------------------------------- дубли

class NeedsReviewFilter(admin.SimpleListFilter):
    """«Нужен разбор» живёт в журнале генераций: lost, частичное списание."""

    title = "нужен разбор"
    parameter_name = "review"

    def lookups(self, request, model_admin):
        return (("1", "Да"), ("0", "Нет"))

    def queryset(self, request, queryset):
        if self.value() == "1":
            return queryset.filter(genlog__needs_review=True)
        if self.value() == "0":
            return queryset.exclude(genlog__needs_review=True)
        return queryset


@admin.register(Take)
class TakeAdmin(admin.ModelAdmin):
    list_display = ("short_uid", "user", "kind", "mode", "model_ref", "status", "charge_state",
                    "credits", "needs_review", "created_at", "finished_at")
    # ?uid=<uid> (ссылка из журнала генераций) — обычный фильтр по полю модели.
    list_filter = ("status", "charge_state", NeedsReviewFilter, "kind", "model_ref", "mode",
                   "created_at")
    search_fields = ("uid", "provider_id", "client_request_id", "user__email", "shot__uid",
                     "project__uid")
    list_select_related = ("user", "genlog")
    ordering = ("-created_at",)
    date_hierarchy = "created_at"
    actions = ("redeliver",)
    fieldsets = (
        ("Дубль", {"fields": ("uid", "user", "project", "shot", "kind", "mode", "model_ref",
                              "status", "stage", "created_at", "submitted_at", "finished_at",
                              "updated_at")}),
        ("Деньги", {
            "fields": ("charge_state", "credits_quoted", "credits_reserved", "credits_charged",
                       "provider_cost_usd"),
            "description": "Резерв ставится при запуске, списание — только за готовый результат. "
                           "Меняет их только конвейер.",
        }),
        ("Журнал генераций", {"fields": ("journal", "journal_stages", "journal_error")}),
        ("Провайдер", {"fields": ("provider_id", "polling_url", "provider_account_id", "provider_key_fp",
                                  "next_poll_at", "poll_count", "poll_errors", "lease_until",
                                  "attempts")}),
        ("Что ушло модели", {"fields": ("serialized_prompt_pretty", "request_body_pretty",
                                        "effective_pretty", "dropped_pretty", "warnings_pretty")}),
        ("Результат и ошибка", {"fields": ("result_asset", "result_preview", "error",
                                           "error_code", "error_input")}),
        ("Служебное", {"fields": ("client_request_id",), "classes": ("collapse",)}),
    )
    readonly_fields = (
        "uid", "user", "project", "shot", "kind", "mode", "model_ref", "status", "stage",
        "created_at", "submitted_at", "finished_at", "updated_at",
        "charge_state", "credits_quoted", "credits_reserved", "credits_charged", "provider_cost_usd",
        "journal", "journal_stages", "journal_error",
        "provider_id", "polling_url", "provider_account_id", "provider_key_fp", "next_poll_at",
        "poll_count", "poll_errors", "lease_until", "attempts",
        "serialized_prompt_pretty", "request_body_pretty", "effective_pretty", "dropped_pretty",
        "warnings_pretty",
        "result_asset", "result_preview", "error", "error_code", "error_input",
        "client_request_id",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        # Открытый дубль держит резерв и его ведёт воркер: удаление «сняло бы»
        # резерв без записи и оставило бы задачу без строки.
        if obj is not None and obj.is_open:
            return False
        return super().has_delete_permission(request, obj)

    def has_redeliver_permission(self, request):
        user = request.user
        return bool(user.is_active and user.is_staff
                    and (user.is_superuser or user.has_perm("vstudio.change_take")))

    # --- колонки списка

    @admin.display(description="uid", ordering="uid")
    def short_uid(self, obj):
        return obj.uid[:8]

    @admin.display(description="Кредиты: цена / резерв / списано")
    def credits(self, obj):
        return f"{obj.credits_quoted} / {obj.credits_reserved} / {obj.credits_charged}"

    @admin.display(description="Разбор", boolean=True)
    def needs_review(self, obj):
        return bool(obj.genlog_id and obj.genlog.needs_review)

    # --- журнал генераций

    @admin.display(description="Запись журнала")
    def journal(self, obj):
        link = journal_url(obj.uid)
        g = obj.genlog
        if g is None:
            # Без записи провайдеру ничего не уходит (fail-closed), но поиск
            # по uid всё равно полезен: вдруг запись есть, а связь не сохранилась.
            return format_html('нет записи · <a href="{}" target="_blank" rel="noopener">'
                               'искать в журнале</a>', link)
        return format_html('<a href="{}" target="_blank" rel="noopener">#{} · {}</a>{}',
                           link, g.pk, g.get_status_display(),
                           " · нужен разбор" if g.needs_review else "")

    @admin.display(description="Ход по шагам")
    def journal_stages(self, obj):
        return _pre(obj.genlog.stages) if obj.genlog_id else "—"

    @admin.display(description="Ошибка в журнале")
    def journal_error(self, obj):
        return _pre(obj.genlog.error) if obj.genlog_id else "—"

    # --- что ушло модели

    @admin.display(description="Текст для модели")
    def serialized_prompt_pretty(self, obj):
        return _pre(obj.serialized_prompt)

    @admin.display(description="Тело запроса")
    def request_body_pretty(self, obj):
        return _pre(obj.request_body)

    @admin.display(description="Фактические параметры")
    def effective_pretty(self, obj):
        return _pre(obj.effective)

    @admin.display(description="Не отправлено")
    def dropped_pretty(self, obj):
        return _pre(obj.dropped)

    @admin.display(description="Предупреждения")
    def warnings_pretty(self, obj):
        return _pre(obj.warnings)

    @admin.display(description="Вид результата")
    def result_preview(self, obj):
        asset = obj.result_asset
        if asset is None:
            return "—"
        return _media_preview(asset.thumb_url or (asset.url if asset.kind == Asset.KIND_IMAGE else ""),
                              height=240)

    # --- «Довезти»

    @admin.action(description="Довезти (повторный опрос и выдача без списания)",
                  permissions=["redeliver"])
    def redeliver(self, request, queryset):
        try:
            from .pipeline import admin_redeliver
        except ImportError as exc:
            self.message_user(request, f"Довоз ещё не подключён (vstudio.pipeline): {exc}",
                              messages.ERROR)
            return None
        rows = list(queryset.filter(status=Take.STATUS_LOST).values_list("pk", "uid"))
        skipped = queryset.exclude(status=Take.STATUS_LOST).count()
        started, failed = [], []
        for pk, uid in rows:
            try:
                # Своя точка сохранения: сбой одного дубля не откатывает остальные
                # (в админке включён ATOMIC_REQUESTS — весь запрос одна транзакция).
                with transaction.atomic():
                    result = admin_redeliver(pk)
            except Exception as exc:  # noqa: BLE001 — показать админу и идти дальше
                logger.exception("vstudio admin redeliver failed take=%s", uid)
                failed.append(f"{uid[:8]}: {exc}")
                continue
            if result is False:
                failed.append(f"{uid[:8]}: отказ")
            else:
                started.append(uid[:8])
        if started:
            self.message_user(request, f"Довоз запущен: {len(started)} ({', '.join(started)}).",
                              messages.SUCCESS)
        if failed:
            self.message_user(request, "Не удалось довезти: " + "; ".join(failed), messages.ERROR)
        if skipped:
            self.message_user(request, f"Пропущено {skipped}: довезти можно только потерянные "
                                       "дубли (lost).", messages.WARNING)
        return None


# ---------------------------------------------------------------- витрина

class ShowcaseItemForm(forms.ModelForm):
    class Meta:
        model = ShowcaseItem
        fields = "__all__"
        help_texts = {
            "category": "Под этим именем ролик стоит в карусели первого экрана. "
                        "«Другое» — своего места в ней нет.",
            "show_prompt": "По запросу работает кнопка «Снять похожее». У работы, снятой с "
                           "первого кадра, вместе с запросом всем станет виден и этот кадр.",
        }

    def clean_take(self):
        # То же правило, что у панели: запасной вход не должен его обходить.
        take = self.cleaned_data["take"]
        if not showcase.can_publish(take):
            raise forms.ValidationError("В витрину пока ставятся только работы сотрудников.")
        return take


@admin.register(ShowcaseItem)
class ShowcaseItemAdmin(admin.ModelAdmin):
    form = ShowcaseItemForm
    list_display = ("preview", "title_or_dash", "category", "sort", "is_active", "show_prompt",
                    "has_clip", "take_link", "author", "created_at")
    list_display_links = ("preview", "title_or_dash")
    list_filter = ("is_active", "category", "show_prompt")
    search_fields = ("title", "take__uid", "take__user__email")
    list_select_related = ("take__result_asset", "take__user")
    ordering = ("sort", "-created_at")
    raw_id_fields = ("take",)
    actions = ("rebuild_clip",)
    fields = ("preview_large", "take", "title", "category", "sort", "is_active", "show_prompt",
              "first_frame", "clip_link", "created_by", "created_at", "updated_at")
    # Лёгкую копию собирает задача — руками файл не подкладывают.
    readonly_fields = ("preview_large", "first_frame", "clip_link", "created_by", "created_at",
                       "updated_at")

    def get_readonly_fields(self, request, obj=None):
        # Работу в строке не подменить: другая работа — это другая строка.
        return self.readonly_fields + (("take",) if obj is not None else ())

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

    @admin.display(description="Лёгкая копия", boolean=True, ordering="clip")
    def has_clip(self, obj):
        # У картинки копии нет и не будет — прочерк, а не «нет».
        return bool(obj.clip) if obj.take.kind == Take.KIND_VIDEO else None

    @admin.display(description="Ролик для ленты (лёгкий)")
    def clip_link(self, obj):
        if not obj.clip:
            return "—"
        return format_html('<a href="{}" target="_blank" rel="noopener">{}</a>', obj.clip.url,
                           obj.clip.name)

    @admin.action(description="Пересобрать лёгкую копию ролика (для лент первого экрана)")
    def rebuild_clip(self, request, queryset):
        pks = list(queryset.filter(take__kind=Take.KIND_VIDEO).values_list("pk", flat=True))
        for pk in pks:
            showcase.request_clip(pk)
        skipped = queryset.count() - len(pks)
        if pks:
            self.message_user(request, f"Сборка поставлена в очередь: {len(pks)}. Копия появится "
                                       "через минуту, до этого на сайте играет исходник.",
                              messages.SUCCESS)
        if skipped:
            self.message_user(request, f"Пропущено {skipped}: картинкам лёгкая копия не нужна.",
                              messages.WARNING)

    @staticmethod
    def _picture(obj) -> str:
        asset = obj.take.result_asset
        if asset is None:
            return ""
        return asset.thumb_url or (asset.url if asset.kind == Asset.KIND_IMAGE else "")

    @admin.display(description="Вид")
    def preview(self, obj):
        return _media_preview(self._picture(obj))

    @admin.display(description="Вид")
    def preview_large(self, obj):
        return _media_preview(self._picture(obj), height=240) if obj.pk else "—"

    @admin.display(description="Первый кадр (с «Показывать запрос» виден всем)")
    def first_frame(self, obj):
        # Ровно та картинка, что уйдёт на сайт: правило одно — showcase.start_frame_url.
        return _media_preview(showcase.start_frame_url(obj.take) or "", height=120) if obj.pk else "—"

    @admin.display(description="Название", ordering="title")
    def title_or_dash(self, obj):
        return obj.title or "—"

    @admin.display(description="Дубль")
    def take_link(self, obj):
        url = reverse("admin:vstudio_take_change", args=[obj.take_id])
        return format_html('<a href="{}">{}</a>', url, obj.take.uid[:8])

    @admin.display(description="Автор", ordering="take__user__email")
    def author(self, obj):
        return obj.take.user

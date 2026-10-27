from django.db import models


class Course(models.Model):
    """Курс EsAI Академии: карточка со ссылкой на сайт автора.

    Оплаты, кабинетов преподавателей и интеграций нет — так в ТЗ (27.10.2026).
    Модель ничего не проверяет: черновик бывает пустым. Правила полей и
    публикации — в academy.panel, ссылок — в academy.links. В Django-админке
    модель не зарегистрирована: мимо панели проверки не работали бы.
    """

    title = models.CharField("Название", max_length=120, blank=True, default="")
    teacher = models.CharField("Преподаватель", max_length=80, blank=True, default="")
    description = models.CharField("Описание", max_length=400, blank=True, default="")
    url = models.CharField("Ссылка на курс", max_length=1000, blank=True, default="")
    # Имя файла при каждой загрузке новое: /media/ кэшируют nginx и Cloudflare.
    cover = models.ImageField("Обложка", upload_to="academy/covers/", max_length=255, blank=True,
                              default="")
    cover_thumb = models.ImageField("Обложка 480", upload_to="academy/covers/", max_length=255,
                                    blank=True, default="")
    cover_width = models.PositiveIntegerField(default=0)
    cover_height = models.PositiveIntegerField(default=0)
    is_published = models.BooleanField("Опубликован", default=False)
    sort_order = models.IntegerField("Порядок", default=0)
    # Последняя публикация. Дата есть, а курс не опубликован — «скрыт»; даты нет — «черновик».
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order", "id"]
        indexes = [models.Index(fields=["is_published", "sort_order", "id"],
                                name="academy_course_public")]
        verbose_name = "Курс Академии"
        verbose_name_plural = "Курсы Академии"

    def __str__(self) -> str:
        return self.title or f"Курс #{self.pk}"

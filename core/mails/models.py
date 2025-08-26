from django.db import models

# Create your models here.

class Mail(models.Model):
    subject = models.CharField(max_length=255, verbose_name="Тема сообщения")
    recipient = models.EmailField(verbose_name="Получатель")
    sent_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата отправки")
    body = models.TextField(verbose_name="Текст сообщения")

    def __str__(self):
        return self.subject
    
    class Meta:
        verbose_name = "Mail"
        verbose_name_plural = "Mails"
        ordering = ['-sent_at']
        

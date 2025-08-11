from django.db import models
from users.models import User

# Create your models here.


class AiProvider(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(unique=True)
    base_url = models.URLField(help_text="API URL", blank=True, null=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    token = models.CharField(max_length=255)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


class AiPromptTemplate(models.Model):
    name = models.CharField(max_length=100, unique=True)
    provider = models.ForeignKey(AiProvider, on_delete=models.CASCADE, related_name='prompt_templates')
    template = models.TextField(help_text="Prompt template text")
    purpose = models.CharField(max_length=255, help_text="Purpose of the prompt template")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    description = models.TextField(blank=True)
    
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='created_prompt_templates')
    usage_count = models.PositiveIntegerField(default=0, help_text="Number of times this template has been used")
    is_active = models.BooleanField(default=True, help_text="Is this template currently active?")
    is_public = models.BooleanField(default=False, help_text="Is this template visible to all users?")
    
    def __str__(self):
        return self.name
    

class AiPromptTemplateFavorite(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='favorite_templates')
    template = models.JSONField(help_text="Template data in JSON format")
    created_at = models.DateTimeField(auto_now_add=True)
        
    def __str__(self):
        return f"{self.user.email} favorite templates"
    
    
    

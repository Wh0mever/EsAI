from rest_framework import serializers
from django.conf import settings
from django.utils.dateformat import format as date_format
import logging

logger = logging.getLogger(__name__)

class UniversalModelSerializer(serializers.ModelSerializer):
    class Meta:
        model = None
        fields = '__all__'

    SENSITIVE_FIELDS = {'password', 'secret', 'token', 'auth_token', 'groups', 'user_permissions'}  # можно дополнять

    def __init__(self, *args, **kwargs):
        model = kwargs.pop('model', None)
        super().__init__(*args, **kwargs)

        if model:
            self.Meta.model = model
            self.fields.clear()

            for field in model._meta.get_fields():
                if field.auto_created and not field.concrete:
                    continue

                field_name = field.name

                if field_name in self.SENSITIVE_FIELDS:
                    continue

                field_type = field.get_internal_type()

                if field_type in ['DateField', 'DateTimeField', 'TimeField']:
                    self.fields[field_name] = serializers.SerializerMethodField()
                elif field_type == 'BooleanField':
                    self.fields[field_name] = serializers.BooleanField()
                elif field_type in ['ForeignKey', 'OneToOneField']:
                    self.fields[field_name] = serializers.PrimaryKeyRelatedField(queryset=field.related_model.objects.all())
                elif field_type == 'ManyToManyField':
                    self.fields[field_name] = serializers.PrimaryKeyRelatedField(queryset=field.related_model.objects.all(), many=True)
                elif field_type in ['IntegerField', 'PositiveIntegerField', 'SmallIntegerField', 'PositiveSmallIntegerField', 'BigAutoField']:
                    self.fields[field_name] = serializers.IntegerField()
                else:
                    try:
                        self.fields[field_name] = serializers.CharField()
                    except Exception:
                        logger.error(f'Error in field creation {field_name} for model {model.__name__}')


    def get_field_value(self, obj, field_name):
        value = getattr(obj, field_name)
        if value is None:
            return None

        field_type = obj._meta.get_field(field_name).get_internal_type()

        if field_type == 'DateField':
            return date_format(value, settings.DATE_FORMAT)
        elif field_type == 'DateTimeField':
            return date_format(value, settings.DATETIME_FORMAT)
        elif field_type == 'TimeField':
            return date_format(value, settings.TIME_FORMAT)
        

        return value

    def get_serializer_method_field_names(self):
        """Определяет, какие поля обрабатываются через get_<field_name>."""
        return [
            field.name for field in self.Meta.model._meta.get_fields()
            if field.get_internal_type() in ['DateField', 'DateTimeField', 'TimeField']
            and field.name not in self.SENSITIVE_FIELDS
        ]

    def __getattr__(self, name):
        if name.startswith('get_') and name[4:] in self.get_serializer_method_field_names():
            field_name = name[4:]
            return lambda obj: self.get_field_value(obj, field_name)
        return super().__getattribute__(name)


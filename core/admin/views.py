from rest_framework import viewsets
from rest_framework.views import APIView
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from .serializers import UniversalModelSerializer
from django.utils.text import capfirst
from .apps_map import APPS_MAP


def get_apps_config():
    config = {}
    for app_name, app_config in APPS_MAP.items():
        config[app_name] = {
            'display': app_config['display'],
            'models': {}
        }

        for model_name, model_config in app_config['models'].items():
            config[app_name]['models'][model_name] = {
                'display': model_config['display']
            }

    return config


def get_fields_display(model):
    fields_display = {}
    for field in model._meta.fields:
        if field.verbose_name:
            field_name = field.verbose_name
        else:
            field_name = capfirst(field.name.replace('_', ' ').lower())

        fields_display[field.name] = field_name
    return fields_display


class UniversalModelViewSet(viewsets.ModelViewSet):

    authentication_classes = []
    permission_classes = []

    """
    A viewset that provides default `list()`, `create()`, `retrieve()`, `update()`, and `destroy()` actions.
    """

    def get_app_config(self):
        app_name = self.kwargs.get('app_name')
        model_name = self.kwargs.get('model_name')
        try:
            if app_name not in APPS_MAP:
                raise NotFound(f"App '{app_name}' is not registered in APPS_MAP")
            if model_name not in APPS_MAP[app_name]['models']:
                raise NotFound(f"Model '{model_name}' is not registered in app '{app_name}'")
        except Exception as ex:
            print(ex)
        return APPS_MAP[app_name]['models'].get(model_name, None)

    def get_queryset(self):
        model = self.get_app_config()['model']
        return model.objects.all()

    def get_serializer_class(self):
        config = self.get_app_config()
        return config.get('serializer', UniversalModelSerializer)

    def get_serializer(self, *args, **kwargs):
        config = self.get_app_config()
        serializer_class = self.get_serializer_class()
        
        if serializer_class == UniversalModelSerializer:
            kwargs['model'] = config['model']

        return serializer_class(*args, **kwargs)

    # ---------- Custom logic ----------
    def list(self, request, *args, **kwargs):
        
        app_name = self.kwargs.get('app_name')
        model_name = self.kwargs.get('model_name')
        
        try:
            response = {
                "data": super().list(request, *args, **kwargs).data,
                "fields_display": get_fields_display(self.get_app_config()['model']),
            }
        except Exception as ex:
            print(f"Error in list: {ex}")
            response = {
                "data": [],
                "fields_display": {}
            }
        
        return Response(response)

    def retrieve(self, request, *args, **kwargs):
        print(f"[ADMIN API] GET detail for {self.kwargs.get('app_name')}")
        return super().retrieve(request, *args, **kwargs)

    def create(self, request, *args, **kwargs):
        print(f"[ADMIN API] POST create for {self.kwargs.get('app_name')}")
        return super().create(request, *args, **kwargs)

    def update(self, request, *args, **kwargs):
        print(f"[ADMIN API] PUT/PATCH update for {self.kwargs.get('app_name')}")
        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        print(f"[ADMIN API] DELETE destroy for {self.kwargs.get('app_name')}")
        return super().destroy(request, *args, **kwargs)


class UniversalFieldsOptionsApiView(APIView):
    authentication_classes = []
    permission_classes = []
    
    exclude_fields = ['id', 'password']

    def get(self, request, app_name, model_name):
        
        try:
            model = APPS_MAP[app_name]['models'].get(model_name, None)['model']
        except Exception as ex:
            print(ex)
            raise NotFound(f"App '{app_name}' is not registered in APPS_MAP")
        
        fields_data = {}
        for field in model._meta.get_fields():
            
            if field.name in self.exclude_fields:
                continue
            
            if field.auto_created and not field.concrete:
                continue
                        
            field_name = field.name
            field_type = field.get_internal_type()
            verbose = capfirst(field.verbose_name) if hasattr(field, "verbose_name") else field_name

            if field_name in UniversalModelSerializer.SENSITIVE_FIELDS:
                continue

            fields_data[field_name] = {
                "label": verbose,
                "type": field_type,
                "required": not field.blank,
                "help_text": field.help_text,
                "choices": getattr(field, 'choices', None),
                "max_length": getattr(field, 'max_length', None),
            }

        return Response(fields_data)
    

class AppsMapApiView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        response = get_apps_config()
        return Response(response)
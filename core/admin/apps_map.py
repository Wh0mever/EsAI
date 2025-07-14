from django.contrib.auth.models import Group, Permission
from users.models import User
from mails.models import Mail
from plans.models import TariffPlan, UserSubscription, GenerationUsage, AddonPurchase
from ai.models import AiProvider, AiToken, AiPromptPreset, AiGenerationLog

APPS_MAP = {
    'users': {
        'display': 'Пользователи',
        'models': {
            'users': {
                'model': User,
                'display': 'Пользователи'
            },
            'groups': {
                'model': Group,
                'display': 'Группы'
            },
        }
    },
    'mails': {
        'display': 'Почта',
        'models': {
            'mail': {
                'model': Mail,
                'display': 'Отправленные сообщения'
            }
        }
    },
    'ai': {
        'display': 'AI',
        'models': {
            'ai_provider': {
                'model': AiProvider,
                'display': 'Провайдеры AI'
            },
            'ai_token': {
                'model': AiToken,
                'display': 'Ключи AI'
            },
            'ai_prompt_preset': {
                'model': AiPromptPreset,
                'display': 'Пресеты AI'
            },
            'ai_generation_log': {
                'model': AiGenerationLog,
                'display': 'Логи генераций AI'
            }
        }
    },
    'plans': {
        'display': 'Планы',
        'models': {
            'tariff_plan': {
                'model': TariffPlan,
                'display': 'Тарифные планы'
            },
            'user_subscription': {
                'model': UserSubscription,
                'display': 'Подписки пользователей'
            },
            'generation_usage': {
                'model': GenerationUsage,
                'display': 'Использование генераций'
            },
            'addon_purchase': {
                'model': AddonPurchase,
                'display': 'Покупка аддонов'
            }
        }
    }
}
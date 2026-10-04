"""python manage.py creators_check [--json]

Сверка программы Creators: по строке на каждый инвариант (I1 OK / I1 FAIL (3) …).
Ничего не меняет. Код возврата 1, если есть хотя бы одно нарушение уровня fail.
"""
from __future__ import annotations

import json
import sys

from django.core.management.base import BaseCommand

from creators import checks


class Command(BaseCommand):
    help = "Сверка инвариантов программы EsAI Creators (только чтение)."

    def add_arguments(self, parser):
        parser.add_argument("--json", action="store_true", dest="as_json",
                            help="Вывести нарушения в JSON.")

    def handle(self, *args, **options):
        violations = checks.run()
        failed = any(v.level == "fail" for v in violations)

        if options.get("as_json"):
            self.stdout.write(json.dumps({
                "ok": not failed,
                "violations": [{"code": v.code, "level": v.level, "count": v.count,
                                "detail": v.detail} for v in violations],
            }, ensure_ascii=False))
        else:
            for code in checks.CODES:
                rows = [v for v in violations if v.code == code]
                if not rows:
                    self.stdout.write(f"{code} OK")
                # Сначала fail: предупреждения не должны заслонять нарушение.
                for v in sorted(rows, key=lambda v: v.level != "fail"):
                    self.stdout.write(f"{code} {v.level.upper()} ({v.count}) {v.detail}")

        if failed:
            sys.exit(1)

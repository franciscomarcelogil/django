from django.core.management.base import BaseCommand
from decimal import Decimal, InvalidOperation
from amortiguador.models import Observacion

class Command(BaseCommand):
    help = "Detecta y corrige valores inválidos en Observacion.valordiagrama. Usa --fix para corregir."

    def add_arguments(self, parser):
        parser.add_argument('--fix', action='store_true', help='Aplica una corrección intentando normalizar o seteando NULL')

    def handle(self, *args, **options):
        bad = []
        total = Observacion.objects.count()
        for r in Observacion.objects.all().values('id','valordiagrama'):
            v = r['valordiagrama']
            try:
                if v is not None:
                    Decimal(str(v))
            except (InvalidOperation, TypeError, ValueError):
                bad.append((r['id'], v))
        self.stdout.write(self.style.WARNING(f"Total Observaciones: {total}"))
        self.stdout.write(self.style.WARNING(f"Inválidas: {len(bad)}"))
        for id_, raw in bad:
            self.stdout.write(f" - id={id_} valordiagrama={raw}")
        if options['fix'] and bad:
            fixed = 0
            for id_, raw in bad:
                o = Observacion.objects.get(id=id_)
                if raw is None:
                    o.valordiagrama = None
                else:
                    s = str(raw).strip().replace(',', '.')
                    try:
                        o.valordiagrama = Decimal(s)
                    except Exception:
                        o.valordiagrama = None
                o.save()
                fixed += 1
            self.stdout.write(self.style.SUCCESS(f"Corregidas {fixed} observaciones"))
        elif options['fix']:
            self.stdout.write(self.style.SUCCESS("No había observaciones inválidas para corregir"))

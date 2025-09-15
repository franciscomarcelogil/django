from django.contrib import admin
from .models import Cliente,Pedido,Amortiguador,Tarea,Operario,Fichaamortiguador,Observacion
# Register your models here.
admin.site.register(Cliente)
admin.site.register(Pedido)
admin.site.register(Amortiguador)
admin.site.register(Tarea)
admin.site.register(Operario)
admin.site.register(Observacion)

admin.site.register(Fichaamortiguador)
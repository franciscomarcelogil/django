from django.contrib import admin

from amortiguador.models.inventario import HistoricoPrecioMaterial
from .models import Cliente,Pedido,Amortiguador,Tarea,Operario,Fichaamortiguador,Observacion, Material, MaterialFichaAmortiguador, MaterialTarea, Notificacion
# Register your models here.
admin.site.register(Cliente)
admin.site.register(Pedido)
admin.site.register(Amortiguador)
admin.site.register(Tarea)
admin.site.register(Operario)
admin.site.register(Observacion)
admin.site.register(Material)
admin.site.register(MaterialFichaAmortiguador)
admin.site.register(MaterialTarea)
admin.site.register(Notificacion)
admin.site.register(HistoricoPrecioMaterial)

admin.site.register(Fichaamortiguador)
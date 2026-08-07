from django.db import models
from django.utils import timezone
from .tecnico import Tarea, Fichaamortiguador
from .clientes import Pedido

class Material(models.Model):
  nombre = models.CharField(max_length=200, default='')
  tipo = models.CharField(max_length=100)
  unidad = models.CharField(max_length=100, default='unidad')
  costo_unidad = models.DecimalField(max_digits=10, decimal_places=2, default=0)
  precio_venta = models.DecimalField(max_digits=10, decimal_places=2, default=0)
  stockActual = models.BigIntegerField(default=0)
  stockMinimo = models.BigIntegerField(default=0)

  stockreservado = models.BigIntegerField(blank=True, null=True, default=0)

class HistoricoPrecioMaterial(models.Model):
  """
  Guarda el histórico de precios de venta de un material.
  fecha_de_vigencia: desde cuándo ese precio es válido
  """
  material = models.ForeignKey(Material, on_delete=models.CASCADE, related_name='historico_precios')
  precio_venta = models.DecimalField(max_digits=10, decimal_places=2)
  fecha_de_vigencia = models.DateTimeField(default=timezone.now, help_text="Fecha desde la cual este precio es válido")
  
  class Meta:
    ordering = ['-fecha_de_vigencia']
  
  def __str__(self):
    return f"{self.material.nombre} - ${self.precio_venta} (vigente desde {self.fecha_de_vigencia.strftime('%d/%m/%Y')})"

class MaterialTarea(models.Model):
    material = models.ForeignKey(Material, on_delete=models.CASCADE)
    tarea = models.ForeignKey(Tarea, on_delete=models.CASCADE)
    stockrecomendado = models.BigIntegerField()
    stockusado = models.BigIntegerField(blank=True, null=True)

class MaterialFichaAmortiguador(models.Model):
  material = models.ForeignKey(Material, on_delete=models.CASCADE)
  fichaamortiguador = models.ForeignKey(Fichaamortiguador, on_delete=models.CASCADE)
  cantidadrecomendada = models.BigIntegerField()

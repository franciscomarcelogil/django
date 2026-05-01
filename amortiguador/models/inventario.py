from django.db import models
from .tecnico import Tarea, Fichaamortiguador

class Material(models.Model):
  nombre = models.CharField(max_length=200, default='')
  tipo = models.CharField(max_length=100)
  unidad = models.CharField(max_length=100, default='unidad')
  costo_unidad = models.DecimalField(max_digits=10, decimal_places=2, default=0)
  precio_venta = models.DecimalField(max_digits=10, decimal_places=2, default=0)
  stockActual = models.BigIntegerField(default=0)
  stockMinimo = models.BigIntegerField(default=0)

  stockreservado = models.BigIntegerField(blank=True, null=True, default=0)

class MaterialTarea(models.Model):
    material = models.ForeignKey(Material, on_delete=models.CASCADE)
    tarea = models.ForeignKey(Tarea, on_delete=models.CASCADE)
    stockrecomendado = models.BigIntegerField()
    stockusado = models.BigIntegerField(blank=True, null=True)

class MaterialFichaAmortiguador(models.Model):
  material = models.ForeignKey(Material, on_delete=models.CASCADE)
  fichaamortiguador = models.ForeignKey(Fichaamortiguador, on_delete=models.CASCADE)
  cantidadrecomendada = models.BigIntegerField()

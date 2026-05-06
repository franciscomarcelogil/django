from django.db import models
from .inventario import Material
from .tecnico import Tarea
class Proveedor(models.Model):
    cuit = models.CharField(max_length=20, unique=True, null=True, blank=True) # NUEVO
    nombre = models.CharField(max_length=200)
    apellido = models.CharField(max_length=200, blank=True, null=True)
    telefono = models.CharField(max_length=20, blank=True, null=True)

class Compra(models.Model):
    material = models.ForeignKey(Material, on_delete=models.CASCADE)
    proveedor = models.ForeignKey(Proveedor, on_delete=models.CASCADE)
    cantidad = models.IntegerField()
    costo_unitario = models.DecimalField(max_digits=10, decimal_places=2)
    fecha_compra = models.DateTimeField(auto_now_add=True)
class MaterialProveedor(models.Model):
  material = models.ForeignKey(Material, on_delete=models.CASCADE)
  proveedor = models.ForeignKey(Proveedor, on_delete=models.CASCADE)
  precio_unitario = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

class Notificacion(models.Model):
  """Notificación creada cuando una tarea no puede iniciarse por falta de stock.
  Guardamos la lista de materiales (JSON) y la fecha de solicitud.
  """
  tarea = models.ForeignKey(Tarea, on_delete=models.CASCADE)
  materiales = models.TextField(help_text='JSON list of missing materials with required/available')
  fecha_solicitud = models.DateTimeField(auto_now_add=True)
  resolved = models.BooleanField(default=False)

  def __str__(self):
    return f"Notificación tarea {self.tarea.id} - { 'resuelta' if self.resolved else 'pendiente' }"

from django.db import models

class Cliente(models.Model):
  nombre = models.CharField(max_length=200)
  apellido = models.CharField(max_length=200)
  dni = models.CharField(max_length=10)
  telefono = models.CharField(max_length=20)
  correo = models.CharField(max_length=100)


class Pedido(models.Model):
  fechaingreso = models.DateField(auto_now_add=True)
  horaingreso = models.TimeField(auto_now_add=True)
  estado = models.CharField(max_length=100)
  fechaSalidaEstimada = models.DateTimeField(blank=True, null=True)
  fechaSalidaReal = models.DateTimeField(blank=True, null=True)
  fecha_finalizacion = models.DateTimeField(blank=True, null=True, help_text="Fecha cuando el pedido cambió a estado terminado")
  cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE)
  total_estimado = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
  cancelado = models.BooleanField(default=False)
  fecha_ultimo_cambio = models.DateTimeField(auto_now=True)
  fecha_presupuesto = models.DateTimeField(null=True, blank=True)


class Comprobante(models.Model):
  pedido = models.OneToOneField(Pedido, on_delete=models.CASCADE, related_name='comprobante')
  fecha_creacion = models.DateTimeField(auto_now_add=True)
  contenido = models.TextField(help_text="Contenido del comprobante (PDF en formato texto)")
  
  def __str__(self):
    return f"Comprobante Pedido #{self.pedido.id}"
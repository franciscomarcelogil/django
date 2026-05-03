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
  fechaSalidaEstimada = models.DateField(blank=True, null=True)
  fechaSalidaReal = models.DateField(blank=True, null=True)
  cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE)
  total_estimado = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
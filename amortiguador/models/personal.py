from django.db import models
from django.contrib.auth.models import User
class Operario(models.Model):
  legajo = models.BigIntegerField()
  nombre = models.CharField(max_length=200)
  apellido = models.CharField(max_length=200)
  estado =models.CharField(max_length=200)
  password = models.CharField(max_length=200)
  # link to Django User (optional)
  user = models.OneToOneField(User, null=True, blank=True, on_delete=models.CASCADE, related_name='operario')
  ROLE_CHOICES = (
    ('operario', 'Operario'),
    ('encargado', 'Encargado'),
    ('encargado_materiales', 'Encargado de Materiales'),
  )
  role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='operario')
from django.db import models
from django_lifecycle import AFTER_UPDATE, hook
from .clientes import Pedido
from .personal import Operario
class Fichaamortiguador (models.Model):
  nombregenerico = models.CharField(max_length=100)
  nroseriegenerico = models.CharField(max_length=100)
  valor_minimo = models.DecimalField(max_digits=10, decimal_places=2, default=0)
  valor_maximo = models.DecimalField(max_digits=10, decimal_places=2, default=0)
  mano_obra_reparacion = models.DecimalField(max_digits=10, decimal_places=2, default=0)



class Amortiguador(models.Model):
  nroSerieamortiguador= models.BigIntegerField()
  tipo = models.CharField(max_length=100)
  fichaamortiguador = models.ForeignKey(Fichaamortiguador, on_delete=models.CASCADE)
  configuracion = models.CharField(max_length=100, default='Sin configurar')

class Tarea(models.Model):
  pedido = models.ForeignKey(Pedido, on_delete=models.CASCADE)
  estado = models.CharField(max_length=20)
  prioridad = models.CharField(max_length=20)
  fechaAsignacion = models.DateField(auto_now_add=True)
  fechaLimite = models.DateField(blank=True, null=True)
  tipoTarea = models.CharField(max_length=100, blank=True, null=True)
  operario = models.ForeignKey(Operario, on_delete=models.CASCADE)
  amortiguador = models.ForeignKey(Amortiguador, on_delete=models.CASCADE)
  fecha_ultimo_cambio = models.DateTimeField(auto_now=True)
  @hook(AFTER_UPDATE, when='tipoTarea', was='reparacion', is_now='control')
  def limpiar_materiales_al_cambiar_a_control(self):
        self.materialtarea_set.all().delete()

class Observacion (models.Model):
  tarea = models.ForeignKey(Tarea, on_delete=models.CASCADE)
  amortiguador = models.ForeignKey(Amortiguador, on_delete=models.CASCADE)
  fechaobservacion= models.DateField(auto_now_add=True)
  horaobservacion = models.TimeField(auto_now_add=True)
  tipoobservacion = models.CharField(max_length=100)
  infoobservacion = models.TextField(blank = True, null=True)
  valordiagrama = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)

  class Meta:
    constraints = [
      models.UniqueConstraint(fields=['tarea', 'tipoobservacion'], name='unique_observacion_por_tipo_tarea')
    ]
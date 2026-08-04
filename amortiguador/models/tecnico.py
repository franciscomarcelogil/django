from django.db import models
from .clientes import Pedido
from .personal import Operario
class Fichaamortiguador (models.Model):
  nombregenerico = models.CharField(max_length=100)
  nroseriegenerico = models.CharField(max_length=100)
  valor_minimo = models.DecimalField(max_digits=10, decimal_places=2, default=0)
  valor_maximo = models.DecimalField(max_digits=10, decimal_places=2, default=0)
  mano_obra_reparacion = models.DecimalField(max_digits=10, decimal_places=2, default=0)
  estado = models.CharField(max_length=20, default='activo')



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
  fecha_inicio_reparacion = models.DateTimeField(null=True, blank=True)
  fecha_finalizacion = models.DateTimeField(null=True, blank=True)
  devuelta = models.BooleanField(default=False)





class Observacion(models.Model):
    tarea = models.OneToOneField('Tarea', on_delete=models.CASCADE, related_name='observacion')
    amortiguador = models.ForeignKey('Amortiguador', on_delete=models.CASCADE)
    fecha = models.DateTimeField(auto_now_add=True)
    
    # Campos de control lógico (necesarios para el if/else en vistas y templates)
    sugerencia_tecnica = models.CharField(max_length=20, choices=[('control', 'Control'), ('reparacion', 'Reparación')], blank=True, null=True)
    valor_diagrama = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    
    # 1. El campo que el operario llena a mano en el formulario
    detalle_operario = models.TextField(blank=True, null=True)
    
    # 2. El campo automático que concatena la sugerencia y la lista de materiales
    detalle_autogenerado = models.TextField(blank=True, null=True)
    
    # 3. Comentario final generado por el sistema al finalizar la tarea
    comentariofinal = models.TextField(blank=True, null=True)
from django.db import models

# Create your models here.
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

class Operario(models.Model):
  legajo = models.BigIntegerField()
  nombre = models.CharField(max_length=200)
  apellido = models.CharField(max_length=200)
  estado =models.CharField(max_length=200)
  password = models.CharField(max_length=200)

class Fichaamortiguador (models.Model):
  nombregenerico = models.CharField(max_length=100)
  nroseriegenerico = models.CharField(max_length=100)
  valor_minimo = models.DecimalField(max_digits=10, decimal_places=2, default=0)
  valor_maximo = models.DecimalField(max_digits=10, decimal_places=2, default=0)



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

class Observacion (models.Model):
  tarea = models.ForeignKey(Tarea, on_delete=models.CASCADE)
  amortiguador = models.ForeignKey(Amortiguador, on_delete=models.CASCADE)
  fechaobservacion= models.DateField(auto_now_add=True)
  horaobservacion = models.TimeField(auto_now_add=True)
  tipoobservacion = models.CharField(max_length=100)
  infoobservacion = models.TextField(blank = True, null=True)
  valordiagrama = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)

class Material(models.Model):
  tipo = models.CharField(max_length=100)
  stockActual = models.BigIntegerField()
  stockMinimo = models.BigIntegerField()
  # stockreservado default 0 to avoid None checks and simplify logic
  stockreservado = models.BigIntegerField(default=0)

class MaterialTarea(models.Model):
  material = models.ForeignKey(Material, on_delete=models.CASCADE)
  tarea = models.ForeignKey(Tarea, on_delete=models.CASCADE)
  stockrecomendado = models.BigIntegerField()
  stockusado = models.BigIntegerField(blank=True, null=True)

class MaterialFichaAmortiguador(models.Model):
  material = models.ForeignKey(Material, on_delete=models.CASCADE)
  fichaamortiguador = models.ForeignKey(Fichaamortiguador, on_delete=models.CASCADE)
  cantidadrecomendada = models.BigIntegerField()

class Proveedor(models.Model):
  nombre = models.CharField(max_length=200)
  apellido = models.CharField(max_length=200)
  telefono = models.CharField(max_length=20)

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



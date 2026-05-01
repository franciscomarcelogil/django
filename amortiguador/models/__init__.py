# tu_app/models/__init__.py
from .clientes import Cliente, Pedido
from .personal import Operario
from .tecnico import Fichaamortiguador, Amortiguador, Tarea, Observacion
from .inventario import Material, MaterialTarea, MaterialFichaAmortiguador
from .compras import Proveedor, MaterialProveedor, Notificacion
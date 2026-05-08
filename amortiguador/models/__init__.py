# tu_app/models/__init__.py
from .clientes import Cliente, Pedido, Comprobante
from .personal import Operario
from .tecnico import Fichaamortiguador, Amortiguador, Tarea, Observacion
from .inventario import Material, MaterialTarea, MaterialFichaAmortiguador, HistoricoPrecioMaterial
from .compras import Proveedor, MaterialProveedor, Notificacion, Compra
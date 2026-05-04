import datetime
import json
from django.db import transaction
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse, HttpResponseForbidden
from django.contrib.auth.decorators import login_required
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from django.conf import settings
from django.core.mail import EmailMessage
from .decorators import role_required
import openpyxl
from decimal import Decimal
from django.db.models import Q

PRECIO_REVISION_BASE = Decimal('20000.00') # Define un costo base para la revisión


from .models import Cliente , Pedido, Operario, Amortiguador, Fichaamortiguador, Tarea, Observacion, Material, MaterialFichaAmortiguador, MaterialTarea, Notificacion

import openpyxl
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from .models import Fichaamortiguador, Material, MaterialFichaAmortiguador

def lista_fichas(request):
    fichas = Fichaamortiguador.objects.all()

    if request.method == 'POST' and 'excel_file' in request.FILES:
        excel_file = request.FILES['excel_file']
        
        try:
            wb = openpyxl.load_workbook(excel_file)
            sheet = wb.active
            
            # 1. Leer los atributos estrictos de Fichaamortiguador (Filas 1 a 5)
            nombre_gen = sheet['B1'].value
            nro_serie = str(sheet['B2'].value) if sheet['B2'].value else ''
            
            if not nombre_gen or not nro_serie:
                messages.error(request, 'El Excel debe tener Nombre Genérico en B1 y Nro Serie en B2.')
                return redirect('lista_fichas')

            val_min = sheet['B3'].value or 0
            val_max = sheet['B4'].value or 0
            mano_obra = sheet['B5'].value or 0

            # Creamos o traemos la ficha
            ficha, created = Fichaamortiguador.objects.get_or_create(
                nombregenerico=nombre_gen,
                nroseriegenerico=nro_serie,
                defaults={
                    'valor_minimo': val_min,
                    'valor_maximo': val_max,
                    'mano_obra_reparacion': mano_obra
                }
            )

            # 2. Leer Materiales (A partir de la fila 8 según el nuevo Excel)
            # A: Nombre, B: Tipo, C: Unidad, D: Cantidad Recomendada
            for row in sheet.iter_rows(min_row=8, values_only=True):
                nombre_mat = row[0]
                tipo_mat = row[1]
                unidad_mat = row[2] or 'unidad'
                cantidad_rec = row[3]
                
                if not nombre_mat: 
                    break # Corta si la fila está vacía
                
                # Material creado respetando estrictamente tus atributos (Sin tocar precios)
                material, mat_created = Material.objects.get_or_create(
                    nombre=nombre_mat,
                    tipo=tipo_mat,
                    defaults={
                        'unidad': unidad_mat,
                        'costo_unidad': 0,
                        'precio_venta': 0,
                        'stockActual': 0,
                        'stockMinimo': 0,
                        'stockreservado': 0
                    }
                )
                
                # Vinculación
                if cantidad_rec and float(cantidad_rec) > 0:
                    MaterialFichaAmortiguador.objects.update_or_create(
                        fichaamortiguador=ficha,
                        material=material,
                        defaults={'cantidadrecomendada': cantidad_rec}
                    )
            
            messages.success(request, '¡Ficha y materiales cargados correctamente respetando los modelos!')
        
        except Exception as e:
            messages.error(request, f'Error al procesar el Excel: {str(e)}')
            
        return redirect('lista_fichas')

    return render(request, 'lista_fichas.html', {'fichas': fichas})


def control_inventario(request):
    # 1. EL BUSCADOR (Usa GET de forma segura)
    query = request.GET.get('q')
    if query:
        materiales = Material.objects.filter(
            Q(nombre__icontains=query) | Q(tipo__icontains=query)
        )
    else:
        materiales = Material.objects.all()

    # 2. EL MODAL DE EDICIÓN Y COMPRA (Usa POST de forma segura)
    if request.method == 'POST':
        # LA SOLUCIÓN AL ERROR: Usar .get() con paréntesis, NUNCA corchetes []
        material_id = request.POST.get('material_id')
        
        # Solo entramos a guardar si de verdad el formulario envió un ID
        if material_id:
            material = get_object_or_404(Material, id=material_id)
            
            nueva_cantidad = request.POST.get('cantidad_compra')
            nuevo_costo = request.POST.get('costo_unidad')
            porcentaje_ganancia = request.POST.get('porcentaje_ganancia')

            try:
                if nueva_cantidad:
                    material.stockActual += int(nueva_cantidad)
                
                if nuevo_costo:
                    material.costo_unidad = Decimal(nuevo_costo)
                    if porcentaje_ganancia:
                        margen = (Decimal(porcentaje_ganancia) / 100) + 1
                        material.precio_venta = material.costo_unidad * margen
                
                # Usamos .get() también aquí con un valor por defecto para que no falle
                stock_min_str = request.POST.get('stock_minimo')
                if stock_min_str:
                    material.stockMinimo = int(stock_min_str)
                    
                material.nombre = request.POST.get('nombre', material.nombre)
                material.tipo = request.POST.get('tipo', material.tipo)
                material.unidad = request.POST.get('unidad', material.unidad)
                
                material.save()
                messages.success(request, f'¡{material.nombre} actualizado correctamente!')
            except Exception as e:
                messages.error(request, f'Error al guardar: {e}')
                
            return redirect('control_inventario')

    return render(request, 'control_inventario.html', {
        'materiales': materiales, 
        'query': query
    })

def detalle_ficha(request, ficha_id):
    ficha = get_object_or_404(Fichaamortiguador, id=ficha_id)
    materiales_ficha = MaterialFichaAmortiguador.objects.filter(fichaamortiguador=ficha)
    
    return render(request, 'detalle_ficha.html', {
        'ficha': ficha,
        'materiales_ficha': materiales_ficha
    })
def _get_request_role(request):
    operario = getattr(request.user, 'operario', None)
    if operario:
        return operario.role
    if getattr(request.user, 'is_superuser', False):
        return 'encargado'
    return None

def sincronizar_estado_pedido(pedido):
    tareas = pedido.tarea_set.all()
    if not tareas.exists():
        return False

    estados = [t.estado for t in tareas]

    if all(e in ['terminada', 'revisada'] for e in estados):
        nuevo_estado = 'terminado'
    elif any(e == 'en reparacion' for e in estados):
        nuevo_estado = 'aprobado' if pedido.estado in ['revisado', 'aprobado'] else pedido.estado
    elif any(e == 'pendiente' for e in estados):
        nuevo_estado = 'en curso'
    elif not any(e == 'pendiente' for e in estados):
        if any(e in ['no revisada', 'por reparar'] for e in estados):
            # PROTECCIÓN: Si el cliente ya aprobó el presupuesto, no lo volvemos atrás
            if pedido.estado == 'aprobado':
                nuevo_estado = 'aprobado'
            else:
                nuevo_estado = 'revisado' 
        else:
            nuevo_estado = pedido.estado
    else:
        nuevo_estado = pedido.estado

    if pedido.estado != nuevo_estado:
        pedido.estado = nuevo_estado
        pedido.save(update_fields=['estado'])
        return True 
        
    return False

def _can_access_tarea(request, tarea):
    if not request.user.is_authenticated:
        return False
    if getattr(request.user, 'is_superuser', False):
        return True
    operario = getattr(request.user, 'operario', None)
    if not operario:
        return False
    if operario.role == 'encargado':
        return True
    return tarea.operario_id == operario.id


def _can_perform_tarea_action(request, tarea, accion):
    role = _get_request_role(request)
    if role is None:
        return False
    if getattr(request.user, 'is_superuser', False):
        return True

    if accion == 'confirmarreparacion':
        return role == 'encargado'

    if accion == 'guardar_tipo_materiales':
        return role == 'encargado'

    if accion == 'agregarmaterialtarea':
        return role == 'encargado'

    if accion in {'terminarobservacioncontrol', 'reservar_materiales', 'finalizartarea'}:
        operario = getattr(request.user, 'operario', None)
        return role == 'operario' and operario is not None and tarea.operario_id == operario.id

    return False


def _validar_fecha_limite_pedido(fecha_limite_raw, pedido):
    if not fecha_limite_raw:
        return None, 'Debes ingresar una fecha limite.'

    try:
        fecha_limite = datetime.date.fromisoformat(fecha_limite_raw)
    except ValueError:
        return None, 'Fecha invalida. Usa un formato correcto (AAAA-MM-DD).'

    hoy = datetime.date.today()
    if fecha_limite < hoy:
        return None, 'La fecha limite no puede ser anterior a hoy.'

    if pedido.fechaingreso and fecha_limite < pedido.fechaingreso:
        return None, 'La fecha limite no puede ser anterior a la fecha de ingreso del pedido.'

    # En amortiguadores no tiene sentido una promesa excesiva a largo plazo para una orden activa.
    if (fecha_limite - hoy).days > 180:
        return None, 'La fecha limite no puede superar 180 dias desde hoy.'

    return fecha_limite, None


def _obtener_presupuesto_estimado(pedido):
    total_revision = Decimal(pedido.tarea_set.count()) * PRECIO_REVISION_BASE
    total_materiales = Decimal('0.00')
    total_mano_obra = Decimal('0.00')

    for tarea in pedido.tarea_set.all():
        # Sumar mano de obra de la ficha del amortiguador
        total_mano_obra += tarea.amortiguador.fichaamortiguador.mano_obra_reparacion
        
        # Sumar materiales que el operario sugirió
        for mat_sugerido in tarea.materialtarea_set.all():
            total_materiales += (mat_sugerido.material.precio_venta * mat_sugerido.stockrecomendado)
            
    return total_revision + total_mano_obra + total_materiales


def _obtener_desglose_presupuesto(pedido):
    """
    Retorna un desglose detallado del presupuesto con:
    - Precio de revisión por tarea
    - Desglose de materiales agrupados (sumando cantidades del mismo material)
    - Mano de obra
    """
    tareas = pedido.tarea_set.all()
    num_tareas = tareas.count()
    precio_revision_total = num_tareas * PRECIO_REVISION_BASE
    
    # Agrupar materiales por tipo de material
    materiales_agrupados = {}
    total_mano_obra = Decimal('0.00')
    
    for tarea in tareas:
        # Sumar mano de obra de la ficha del amortiguador
        total_mano_obra += tarea.amortiguador.fichaamortiguador.mano_obra_reparacion
        
        # Agrupar materiales
        for mat_sugerido in tarea.materialtarea_set.all():
            material_id = mat_sugerido.material.id
            if material_id not in materiales_agrupados:
                materiales_agrupados[material_id] = {
                    'nombre': mat_sugerido.material.tipo,
                    'precio_unitario': mat_sugerido.material.precio_venta,
                    'cantidad_total': Decimal('0'),
                }
            materiales_agrupados[material_id]['cantidad_total'] += mat_sugerido.stockrecomendado
    
    # Construir lista de materiales con subtotales
    desglose_materiales = []
    total_materiales = Decimal('0.00')
    for mat_data in materiales_agrupados.values():
        subtotal = mat_data['cantidad_total'] * mat_data['precio_unitario']
        total_materiales += subtotal
        desglose_materiales.append({
            'material': mat_data['nombre'],
            'cantidad': mat_data['cantidad_total'],
            'precio_unitario': mat_data['precio_unitario'],
            'subtotal': subtotal,
        })
    
    # Calcular total general
    total_general = precio_revision_total + total_materiales + total_mano_obra
    
    return {
        'num_tareas': num_tareas,
        'precio_revision_unitario': PRECIO_REVISION_BASE,
        'precio_revision_total': precio_revision_total,
        'desglose_materiales': sorted(desglose_materiales, key=lambda x: x['material']),
        'total_materiales': total_materiales,
        'total_mano_obra': total_mano_obra,
        'total_general': total_general,
    }


def _materiales_para_sugerencia_tarea(tarea):
    materiales_ficha = MaterialFichaAmortiguador.objects.select_related('material').filter(
        fichaamortiguador=tarea.amortiguador.fichaamortiguador
    )
    materiales_tarea = {
        item.material_id: item.stockrecomendado
        for item in MaterialTarea.objects.filter(tarea=tarea)
    }

    return [
        {
            'material_id': item.material_id,
            'material_tipo': item.material.tipo,
            'cantidad_maxima': item.cantidadrecomendada,
            'cantidad_sugerida': materiales_tarea.get(item.material_id, 0),
        }
        for item in materiales_ficha
    ]


def _observacion_para_tarea(tarea, tipoobservacion):
    return Observacion.objects.filter(tarea=tarea, tipoobservacion=tipoobservacion).first()


def _actualizar_estado_pedido_si_corresponde(pedido):
    tareas_pedido = Tarea.objects.filter(pedido=pedido)
    if tareas_pedido.exists() and tareas_pedido.exclude(estado='terminada').count() == 0:
        if pedido.estado != 'terminado':
            pedido.estado = 'terminado'
            pedido.save(update_fields=['estado'])
        return True
    return False


def _pdf_escape(text):
    return str(text).replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')


def _generar_comprobante_pdf(pedido, tareas):
    fecha_actual = datetime.date.today().strftime('%d/%m/%Y')
    cliente = f"{pedido.cliente.nombre} {pedido.cliente.apellido}".strip()
    lineas = [
        f"Comprobante de pedido #{pedido.id}",
        f"Fecha: {fecha_actual}",
        f"Cliente: {cliente}",
        f"DNI: {pedido.cliente.dni}",
        f"Presupuesto total: ${_obtener_presupuesto_estimado(pedido)}",

        "",
        "Tareas incluidas:",
    ]

    if tareas.exists():
        for tarea in tareas:
            lineas.append(
                f"- Tarea {tarea.id} | Serie: {tarea.amortiguador.nroSerieamortiguador} | Estado: {tarea.estado}"
            )
    else:
        lineas.append("- Sin tareas asociadas")

    comandos = ["BT", "/F1 11 Tf", "40 800 Td"]
    for index, linea in enumerate(lineas):
        if index > 0:
            comandos.append("0 -16 Td")
        comandos.append(f"({_pdf_escape(linea)}) Tj")
    comandos.append("ET")

    contenido_stream = "\n".join(comandos) + "\n"
    stream_bytes = contenido_stream.encode('latin-1', errors='replace')

    objetos = [
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n",
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>\nendobj\n",
        f"4 0 obj\n<< /Length {len(stream_bytes)} >>\nstream\n".encode('ascii') + stream_bytes + b"endstream\nendobj\n",
        b"5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n",
    ]

    pdf = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for obj in objetos:
        offsets.append(len(pdf))
        pdf.extend(obj)

    xref_pos = len(pdf)
    pdf.extend(f"xref\n0 {len(objetos) + 1}\n".encode('ascii'))
    pdf.extend(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        pdf.extend(f"{off:010d} 00000 n \n".encode('ascii'))

    pdf.extend(
        f"trailer\n<< /Size {len(objetos) + 1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF".encode('ascii')
    )
    return bytes(pdf)


def home(request):
    return render(request, 'home.html')


def login_view(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            return redirect('home')
        else:
            messages.error(request, 'Usuario o contraseña incorrectos.')
    return render(request, 'login.html')

@role_required(['encargado'])
def createpedido(request):
        context = {}
        if request.method == 'POST':
            accion = request.POST.get('accion')
            dni = request.POST.get('dni')
            context['dni'] = dni
            if accion == 'buscar_cliente':
                try:
                    cliente = Cliente.objects.get(dni=dni)
                    context['cliente'] = cliente
                except Cliente.DoesNotExist:
                    context['cliente_no_encontrado'] = True
                return render(request, 'createpedido.html', context)
            elif accion == 'crear_cliente_pedido':
                cliente = Cliente.objects.create( 
                    nombre=request.POST.get('nombre'),
                    apellido=request.POST.get('apellido'),
                    dni=request.POST.get('dni'),
                    telefono=request.POST.get('telefono'),
                    correo=request.POST.get('correo')
                )
                pedido = Pedido.objects.create(
                    estado='pendiente',
                    cliente=cliente
                )
                return redirect('detalle_pedido', pedido_id=pedido.id)
            elif accion == 'crear_pedido':
                try:
                    id_cliente = request.POST.get('cliente_id')
                    cliente = Cliente.objects.get(id=id_cliente)
                    pedido = Pedido.objects.create(
                        estado='pendiente',
                        cliente=cliente
                    )
                    return redirect('detalle_pedido', pedido_id=pedido.id)
                except Cliente.DoesNotExist:
                    context['error'] = "No se puede crear el pedido. Cliente no encontrado."

        return render(request, 'createpedido.html', context)
    
@role_required(['encargado'])
def detalle_pedido(request, pedido_id):
    pedido = get_object_or_404(Pedido, id=pedido_id)
    tareas = Tarea.objects.select_related('amortiguador').filter(pedido=pedido)
    editar_plan = request.GET.get('editar_plan') == '1'
    
    mensaje_exito = None

    tareas_reparacion_editables = tareas.filter(tipoTarea='reparacion', estado='por reparar')
    control= not(tareas.filter(tipoTarea='reparacion').exists())
    todastareasrevisadas = not tareas.exclude(estado__in=['revisada', 'por reparar']).exists() if tareas.exists() else False
    
    presupuesto_estimado = 0
    desglose_presupuesto = None
    if pedido.estado == 'revisado':
        presupuesto_estimado = _obtener_presupuesto_estimado(pedido)
        desglose_presupuesto = _obtener_desglose_presupuesto(pedido)
    


    if request.method == 'POST':
        accion = request.POST.get('accion')
        if accion == 'terminar_revision_pedido':
            # Validar que todas las tareas tengan tipo definido
            tareas_sin_tipo = tareas.filter(tipoTarea__isnull=True) | tareas.filter(tipoTarea='')
            if tareas_sin_tipo.exists():
                messages.error(request, 'No puedes terminar la revisión si hay tareas sin tipo definido.')
                return redirect('detalle_pedido', pedido_id=pedido.id)
            
            # MAGIA: La función deduce sola si va a "revisado" o a "terminado"
            sincronizar_estado_pedido(pedido)
            
            if pedido.estado == 'revisado':
                messages.success(request, 'Revisión completada. Ya puedes solicitar la aprobación del presupuesto al cliente.')
            else:
                messages.success(request, '¡El pedido ha sido finalizado como control (Sin repuestos)!')
            
            return redirect('detalle_pedido', pedido_id=pedido.id)
        elif accion == 'crear_tarea':
            return redirect('create_tarea', pedido_id=pedido.id)

        elif accion == 'finalizar_creacion_pedido':
            # Cambiamos el estado para que el pedido sea "oficial"
            # Supongamos que el siguiente estado lógico es 'revisado' o 'en curso'
            pedido.estado = 'en curso' # O el estado que uses para tareas ya asignadas
            pedido.save()
            messages.success(request, "Pedido confirmado y tareas asignadas a los operarios.")
            return redirect('home')

        elif accion == 'borrar_pedido':
            # Borrado en cascada (asegúrate que en models.py tengas on_delete=models.CASCADE)
            pedido.delete()
            messages.warning(request, "Se canceló la creación del pedido y se eliminaron los datos asociados.")
            return redirect('home')        
        elif accion == 'aprobar_presupuesto':
            if pedido.estado == 'revisado':
                # 1. Calcular y guardar el total definitivo aceptado
                total = _obtener_presupuesto_estimado(pedido)
                pedido.total_estimado = total
                
                if tareas.filter(tipoTarea='reparacion').exists():
                    pedido.estado = 'aprobado'
                    # ELIMINAMOS EL BUCLE DE RESTA DE STOCK ACÁ.
                    # Solo informamos que ya se puede arrancar.
                    messages.success(request, f'Presupuesto de ${total} aprobado. Las tareas están habilitadas para que los operarios reserven el stock y comiencen.')
                else:
                    pedido.estado = 'terminado'
                    messages.success(request, '¡El pedido ha sido finalizado como control, avisale al cliente!')

                pedido.save()

            else:
                messages.error(request, 'Solo se puede aprobar si el pedido está revisado.')
            return redirect('detalle_pedido', pedido_id=pedido.id)
        elif accion == 'finalizar_pedido':
            fecha_limite_raw = request.POST.get('fecha_limite')
            fecha_limite, error = _validar_fecha_limite_pedido(fecha_limite_raw, pedido)
            if error:
                messages.error(request, error)
                return redirect('detalle_pedido', pedido_id=pedido.id)

            tareas.exclude(estado='terminada').update(fechaLimite=fecha_limite)
            pedido.fechaSalidaEstimada = fecha_limite
            pedido.save(update_fields=['fechaSalidaEstimada'])
            messages.success(request, 'Fecha limite asignada correctamente al pedido y sus tareas activas.')
            return redirect('detalle_pedido', pedido_id=pedido.id)
        elif accion == 'actualizar_plan':
            if pedido.estado != 'revisado':
                messages.error(request, 'El plan solo puede modificarse cuando el pedido está siendo revisado.')
                return redirect('detalle_pedido', pedido_id=pedido.id)

            fecha_limite_raw = request.POST.get('fecha_limite')
            fecha_limite, error = _validar_fecha_limite_pedido(fecha_limite_raw, pedido)
            if error:
                messages.error(request, error)
                return redirect('detalle_pedido', pedido_id=pedido.id)

            tareas.exclude(estado='terminada').update(fechaLimite=fecha_limite)
            pedido.fechaSalidaEstimada = fecha_limite
            pedido.save(update_fields=['fechaSalidaEstimada'])
            messages.success(request, 'Plan actualizado. Puedes editar materiales desde cada tarea de reparacion.')
            return redirect('detalle_pedido', pedido_id=pedido.id)
        elif accion == 'marcar_listo_retirar':
            if pedido.estado not in ('terminado', 'revisado')  :
                messages.error(request, 'Solo los pedidos terminados pueden pasar a listo para retirar.')
                return redirect('detalle_pedido', pedido_id=pedido.id)
            

            pedido.estado = 'listo para retirar'
            pedido.save(update_fields=['estado'])
            messages.success(request, 'Pedido marcado como listo para retirar.')
            return redirect('detalle_pedido', pedido_id=pedido.id)
        elif accion == 'emitir_comprobante':
            if pedido.estado not in ('terminado', 'listo para retirar', 'revisado'):
                messages.error(request, 'El comprobante solo se puede emitir para pedidos terminados o listos para retirar.')
                return redirect('detalle_pedido', pedido_id=pedido.id)

            pdf_bytes = _generar_comprobante_pdf(pedido, tareas)
            response = HttpResponse(pdf_bytes, content_type='application/pdf')
            response['Content-Disposition'] = f'attachment; filename="comprobante_pedido_{pedido.id}.pdf"'
            return response
        elif accion == 'enviar_comprobante':
            if pedido.estado not in ('terminado', 'listo para retirar', 'revisado'):
                messages.error(request, 'El comprobante solo se puede enviar para pedidos terminados o listos para retirar.')
                return redirect('detalle_pedido', pedido_id=pedido.id)

            destino = (pedido.cliente.correo or '').strip()
            if not destino:
                messages.error(request, 'El cliente no tiene correo cargado.')
                return redirect('detalle_pedido', pedido_id=pedido.id)

            try:
                pdf_bytes = _generar_comprobante_pdf(pedido, tareas)
                mail = EmailMessage(
                    subject=f'Comprobante pedido #{pedido.id}',
                    body=(
                        f'Hola {pedido.cliente.nombre},\n\n'
                        f'Tu pedido #{pedido.id} se encuentra {pedido.estado}.\n'
                        'Adjuntamos el comprobante en PDF.\n\n'
                        'Saludos.'
                    ),
                    to=[destino],
                )
                mail.attach(f'comprobante_pedido_{pedido.id}.pdf', pdf_bytes, 'application/pdf')
                mail.send(fail_silently=False)
                if settings.EMAIL_BACKEND == 'django.core.mail.backends.console.EmailBackend':
                    messages.warning(
                        request,
                        f'Comprobante generado para {destino}, pero el proyecto esta en modo consola (no se envio un mail real).'
                    )
                else:
                    messages.success(request, f'Comprobante enviado a {destino}.')
            except Exception as exc:
                messages.error(request, f'No se pudo enviar el comprobante: {exc}')

            return redirect('detalle_pedido', pedido_id=pedido.id)
        elif accion == 'retirar_pedido':
            if pedido.estado != 'listo para retirar':
                messages.error(request, 'Solo los pedidos listos para retirar pueden ser retirados.')
                return redirect('detalle_pedido', pedido_id=pedido.id)

            pedido.estado = 'retirado'
            pedido.save()
            messages.success(request, 'Pedido marcado como retirado')
            return redirect('detalle_pedido', pedido_id=pedido.id)

    context = {
        'pedido': pedido,
        'tareas': tareas,
        'mensaje_exito': mensaje_exito,
        'editar_plan': editar_plan,
        'tareas_reparacion_editables': tareas_reparacion_editables,
        'presupuesto_estimado': presupuesto_estimado,
        'desglose_presupuesto': desglose_presupuesto,
        'control': control,
        'todastareasrevisadas': todastareasrevisadas,
    }
    return render(request, 'detalle_pedido.html', context)


def create_tarea(request, pedido_id):
    operarios = Operario.objects.filter(role='operario')
    fichas = Fichaamortiguador.objects.all()
    pedido = get_object_or_404(Pedido, id=pedido_id)
    context = { 'operarios': operarios, 'fichas': fichas, 'pedido': pedido }
    if request.method == 'POST':
        accion = request.POST.get('accion')
        if accion == 'buscar':
            try:
                amortiguador = Amortiguador.objects.get(nroSerieamortiguador=request.POST.get('nroSerieamortiguador'))
                context['amortiguador'] = amortiguador
            except Amortiguador.DoesNotExist:
                context['no_amortiguador'] = True
                context['nroSerieamortiguador'] = request.POST.get('nroSerieamortiguador')
        elif accion == 'crear_amortiguador_tarea':
            ficha = get_object_or_404(Fichaamortiguador, id = request.POST.get('ficha_amortiguador'))
            amortiguador = Amortiguador.objects.create(
                fichaamortiguador = ficha,
                nroSerieamortiguador = request.POST.get('nroSerieamortiguador'),
                tipo = request.POST.get('tipo_amortiguador')
            )
            operario = get_object_or_404(Operario,id = request.POST.get('operario'))
            tarea = Tarea.objects.create(
                prioridad = request.POST.get('prioridad'),
                amortiguador = amortiguador,
                operario = operario,
                pedido = pedido,
                estado = 'pendiente'
                
            ) 
            return redirect('detalle_pedido', pedido_id=pedido.id)
        elif accion =='crear_tarea':
            operario = get_object_or_404(Operario,id = request.POST.get('operario'))
            amortiguador = get_object_or_404(Amortiguador, id = request.POST.get('id_amortiguador'))
            tarea = Tarea.objects.create(
                prioridad = request.POST.get('prioridad'),
                amortiguador = amortiguador,
                operario = operario,
                pedido = pedido,
                estado = 'pendiente'
            ) 
            return redirect('detalle_pedido', pedido_id=pedido.id)

    return render(request, 'create_tarea.html', context)


@login_required
@role_required(['operario'])
def paneltareas(request):
    operarios = Operario.objects.filter(role='operario')
    context = { 'operarios': operarios }
    # operario vinculado al usuario (si existe)
    user_operario = getattr(request.user, 'operario', None)
    if user_operario:
        context['operario'] = user_operario
    if request.method == 'POST':
        accion = request.POST.get('accion')
        estadoselect = request.POST.get('estado')
        context['estadoselect'] = estadoselect
        priority = request.POST.get('prioridad')
        context['priority'] = priority
        if accion == 'elegiroperario':
            operario_id = request.POST.get('operario')

            if operario_id:
                operario = get_object_or_404(Operario, id=operario_id)
            else:
                operario = user_operario
            if not operario:
                context['error'] = 'No hay un operario asignado al usuario. Selecciona uno o contacta al administrador.'
                return render(request, 'paneltareas.html', context)
            tareas = Tarea.objects.filter(operario=operario)
            if estadoselect:
                tareas = tareas.filter(estado=estadoselect)
            if priority:
                tareas = tareas.filter(prioridad=priority)
            
            # Ordenamiento por prioridad y luego por fecha de último cambio
            tareas = tareas.order_by('-prioridad', 'fecha_ultimo_cambio')

            context['tareas'] = tareas
            context['operario'] = operario

            if estadoselect:
                context['titulo_tareas'] = f"Tareas con estado '{estadoselect}'"
            else:
                context['titulo_tareas'] = "Tareas Pendientes"

    if request.method == 'GET' and user_operario:
        tareas = Tarea.objects.filter(operario=user_operario).exclude(estado='terminada').order_by('-prioridad', 'fecha_ultimo_cambio')
        context['tareas'] = tareas
        context['titulo_tareas'] = "Mis tareas activas"
    return render(request, 'paneltareas.html', context)



@role_required(['operario', 'encargado'])
def detalle_tarea(request, tarea_id):
    tarea = get_object_or_404(Tarea, id=tarea_id)
    if not _can_access_tarea(request, tarea):
        return HttpResponseForbidden('No tienes permisos para ver esta tarea.')

    context = {'tarea': tarea, 'user_role': _get_request_role(request)}
    
    # Traemos la observación unificada (si existe)
    observacion = Observacion.objects.filter(tarea=tarea).first()
    context['observacion'] = observacion
    
    materialxamortiguador = MaterialFichaAmortiguador.objects.filter(fichaamortiguador=tarea.amortiguador.fichaamortiguador)
    materialxtarea = MaterialTarea.objects.filter(tarea=tarea)
    
    context['materialxtarea'] = materialxtarea
    context['materialxamortiguador'] = materialxamortiguador
    context['materiales_sugeribles'] = _materiales_para_sugerencia_tarea(tarea)
    
    # Extraer sugerencia de tipo directamente de la observación unificada
    tipo_sugerido = observacion.sugerencia_tecnica if observacion else None
    context['tipo_sugerido'] = tipo_sugerido

    if request.method == 'POST':
        accion = request.POST.get('accion')
        if not _can_perform_tarea_action(request, tarea, accion):
            return HttpResponseForbidden('No tienes permisos para realizar esta acción.')

        # -------------------------------------------------------------------
        # ACCIÓN 1: EL OPERARIO TERMINA EL DIAGNÓSTICO
        # -------------------------------------------------------------------
        if accion == 'terminarobservacioncontrol':
            if tarea.estado != 'pendiente':
                messages.error(request, 'Solo puedes cerrar observaciones cuando la tarea esta pendiente.')
                return redirect('detalle_tarea', tarea_id=tarea.id)

            if not observacion:
                messages.error(request, 'Debes cargar el diagnóstico antes de cerrar la revision.')
                return redirect('detalle_tarea', tarea_id=tarea.id)

            tarea.estado = 'no revisada'
            tarea.save(update_fields=['estado'])
            
            # MAGIA: Sincronizamos el pedido
            cambio_pedido = sincronizar_estado_pedido(tarea.pedido)
            
            context['class'] = 'alert alert-success'
            context['message'] = 'Has finalizado las observaciones de control de calidad.'
            
            if cambio_pedido and tarea.pedido.estado == 'revisado':
                messages.info(request, 'Todas las tareas fueron diagnosticadas. El pedido pasó a revisión del encargado.')
                
            return redirect('home')
            
        # -------------------------------------------------------------------
        # ACCIÓN 2: EL ENCARGADO DEFINE SI ES CONTROL O REPARACIÓN
        # -------------------------------------------------------------------
        elif accion == 'guardar_tipo_materiales':
            if tarea.estado not in ('no revisada', 'revisada', 'por reparar'):
                messages.error(request, 'Solo puedes guardar tipo y materiales cuando la tarea esta en revision o por reparar.')
                return redirect('detalle_tarea', tarea_id=tarea.id)

            nuevo_tipo = (request.POST.get('tipoTarea') or '').strip()
            if nuevo_tipo not in ('control', 'reparacion'):
                messages.error(request, 'Tipo invalido.')
                return redirect('detalle_tarea', tarea_id=tarea.id)

            material_ids = request.POST.getlist('material_id[]')
            cantidades = request.POST.getlist('cantidadrecomendada[]')
            mapa_recomendados = {
                str(item.material_id): int(item.cantidadrecomendada or 0)
                for item in MaterialFichaAmortiguador.objects.filter(fichaamortiguador=tarea.amortiguador.fichaamortiguador)
            }

            materiales_para_guardar = []
            for material_id, cantidad_raw in zip(material_ids, cantidades):
                try:
                    if material_id not in mapa_recomendados:
                        messages.error(request, 'Se detecto un material invalido para esta ficha tecnica.')
                        return redirect('detalle_tarea', tarea_id=tarea.id)

                    material = Material.objects.get(id=material_id)
                    cantidad_int = int(cantidad_raw)
                    if cantidad_int < 0:
                        messages.error(request, f'Cantidad invalida para {material.tipo}. No puede ser negativa.')
                        return redirect('detalle_tarea', tarea_id=tarea.id)

                    max_recomendado = int(mapa_recomendados.get(material_id, 0))
                    if cantidad_int > max_recomendado:
                        messages.error(request, f'Cantidad invalida para {material.tipo}. El maximo para esta ficha es {max_recomendado}.')
                        return redirect('detalle_tarea', tarea_id=tarea.id)

                    if cantidad_int >= 1:
                        materiales_para_guardar.append((material, cantidad_int))
                except (Material.DoesNotExist, ValueError):
                    messages.error(request, 'Hay cantidades invalidas. Revisa los valores ingresados.')
                    return redirect('detalle_tarea', tarea_id=tarea.id)

            if nuevo_tipo == 'reparacion' and not materiales_para_guardar:
                messages.error(request, 'Debes aprobar al menos un material para reparación.')
                return redirect('detalle_tarea', tarea_id=tarea.id)

            tipo_actual = (tarea.tipoTarea or '').strip()
            cambio_de_tipo = tipo_actual != nuevo_tipo

            with transaction.atomic():
                tarea.tipoTarea = nuevo_tipo
                # Acá se asigna el estado correctamente
                tarea.estado = 'por reparar' if nuevo_tipo == 'reparacion' else 'revisada'
                tarea.save(update_fields=['tipoTarea', 'estado'])

                MaterialTarea.objects.filter(tarea=tarea).delete()
                if nuevo_tipo == 'reparacion':
                    for material, cantidad_int in materiales_para_guardar:
                        MaterialTarea.objects.create(
                            tarea=tarea,
                            material=material,
                            stockrecomendado=cantidad_int,
                        )

            # MAGIA: Sincronizamos por si al pasarla a 'control' el pedido se termina
            sincronizar_estado_pedido(tarea.pedido)

            if cambio_de_tipo:
                messages.success(request, 'Tipo y materiales guardados correctamente.')
            else:
                messages.success(request, 'Materiales actualizados correctamente.')

            # (Acá eliminamos el tarea.estado = 'revisada' que tenías pisando el estado anterior)
            return redirect('detalle_tarea', tarea_id=tarea.id)
        
        # -------------------------------------------------------------------
        # ACCIÓN 3: EL ENCARGADO CONFIRMA REPARACIÓN RÁPIDA (Legacy)
        # -------------------------------------------------------------------
        elif accion == 'confirmarreparacion':
            # ... (Toda la validación inicial de confirmarreparacion queda igual) ...
            nuevo_tipo = request.POST.get('confirmarreparacion')
            tipo_actual = (tarea.tipoTarea or '').strip()
            cambio_de_tipo = tipo_actual != nuevo_tipo

            if nuevo_tipo == 'control' and MaterialTarea.objects.filter(tarea=tarea).exists():
                MaterialTarea.objects.filter(tarea=tarea).delete()

            tarea.tipoTarea = nuevo_tipo
            tarea.estado = 'revisada' if nuevo_tipo == 'control' else 'por reparar'
            tarea.save(update_fields=['tipoTarea', 'estado'])
            
            # MAGIA: Sincronizamos
            sincronizar_estado_pedido(tarea.pedido)
            
            messages.success(request, f'La tarea quedó confirmada como {nuevo_tipo}.')
            return redirect('detalle_tarea', tarea_id=tarea.id)

        # -------------------------------------------------------------------
        # ACCIÓN 4: EL OPERARIO RESERVA MATERIALES
        # -------------------------------------------------------------------
        elif accion == 'reservar_materiales':
            if tarea.estado != 'por reparar':
                messages.error(request, 'La tarea no esta en estado por reparar.')
                return redirect('detalle_tarea', tarea_id=tarea.id)

            faltantes = []
            faltantes_detalle = []
            with transaction.atomic():
                materiales_tarea = MaterialTarea.objects.select_related('material').filter(tarea=tarea)
                if not materiales_tarea.exists():
                    messages.error(request, 'La tarea no tiene materiales cargados para reservar.')
                    return redirect('detalle_tarea', tarea_id=tarea.id)

                for mt in materiales_tarea:
                    mat = Material.objects.select_for_update().get(id=mt.material_id)
                    reservado = int(mat.stockreservado or 0)
                    actual = int(mat.stockActual or 0)
                    requerido = int(mt.stockrecomendado or 0)
                    disponible = actual - reservado
                    if requerido > disponible:
                        disponible_positivo = max(disponible, 0)
                        faltantes.append(
                            f"{mat.tipo}: requiere {requerido}, disponible {disponible_positivo}"
                        )
                        faltantes_detalle.append({
                            'material_id': mat.id,
                            'material': mat.tipo,
                            'requerido': requerido,
                            'disponible': disponible_positivo,
                        })

                if faltantes:
                    existente = Notificacion.objects.filter(
                        tarea=tarea,
                        resolved=False,
                    ).order_by('-fecha_solicitud').first()

                    if existente:
                        # Una sola notificacion pendiente por tarea: se actualiza el detalle.
                        existente.materiales = json.dumps(faltantes_detalle, ensure_ascii=True)
                        existente.save(update_fields=['materiales'])
                    else:
                        Notificacion.objects.create(
                            tarea=tarea,
                            materiales=json.dumps(faltantes_detalle, ensure_ascii=True),
                        )

                    messages.error(request, 'No hay stock suficiente para reservar: ' + '; '.join(faltantes))
                    return redirect('detalle_tarea', tarea_id=tarea.id)

                for mt in materiales_tarea:
                    mat = Material.objects.select_for_update().get(id=mt.material_id)
                    incremento = int(mt.stockrecomendado or 0)
                    mat.stockreservado = int(mat.stockreservado or 0) + incremento
                    mat.save(update_fields=['stockreservado'])

                # Si se pudo reservar, las notificaciones pendientes de esta tarea quedan resueltas.
                Notificacion.objects.filter(tarea=tarea, resolved=False).update(resolved=True)

                tarea.estado = 'en reparacion'
                tarea.save(update_fields=['estado'])
                
            # MAGIA: Le avisamos al pedido
            sincronizar_estado_pedido(tarea.pedido)

            messages.success(request, 'Materiales reservados correctamente.')
            return redirect('detalle_tarea', tarea_id=tarea.id)

        # -------------------------------------------------------------------
        # ACCIÓN 5: EL OPERARIO FINALIZA LA TAREA
        # -------------------------------------------------------------------
        elif accion == 'finalizartarea':
            if tarea.estado != 'en reparacion':
                messages.error(request, 'Solo se puede finalizar una tarea en reparacion.')
                return redirect('detalle_tarea', tarea_id=tarea.id)

            errores = []
            consumos_tarea = []
            consumo_por_material = {}
            reserva_por_material = {}

            with transaction.atomic():
                materiales_tarea = MaterialTarea.objects.select_related('material').filter(tarea=tarea)
                if not materiales_tarea.exists():
                    messages.error(request, 'La tarea no tiene materiales cargados para finalizar.')
                    return redirect('detalle_tarea', tarea_id=tarea.id)

                for mt in materiales_tarea:
                    valor_usado = request.POST.get(f'stockusado_{mt.id}', mt.stockrecomendado)
                    try:
                        usado = int(valor_usado)
                    except (TypeError, ValueError):
                        errores.append(f'Cantidad usada invalida para {mt.material.tipo}.')
                        continue

                    if usado < 0:
                        errores.append(f'Cantidad usada negativa para {mt.material.tipo}.')
                        continue

                    reservado_tarea = int(mt.stockrecomendado or 0)
                    material_id = mt.material_id

                    consumo_por_material[material_id] = int(consumo_por_material.get(material_id, 0)) + usado
                    reserva_por_material[material_id] = int(reserva_por_material.get(material_id, 0)) + reservado_tarea
                    consumos_tarea.append((mt, usado))

                for material_id, total_usado in consumo_por_material.items():
                    mat = Material.objects.select_for_update().get(id=material_id)
                    reservado_total = int(mat.stockreservado or 0)
                    actual = int(mat.stockActual or 0)
                    reservado_tarea = int(reserva_por_material.get(material_id, 0))

                    if reservado_tarea > reservado_total:
                        errores.append(f'Reserva inconsistente para {mat.tipo}.')
                        continue

                    extra = max(total_usado - reservado_tarea, 0)
                    libre = actual - reservado_total
                    if extra > libre:
                        errores.append(
                            f"Stock insuficiente en {mat.tipo}: falta {extra - max(libre, 0)} adicional(es)."
                        )
                        continue

                    if total_usado > actual:
                        errores.append(f'Stock actual insuficiente para {mat.tipo}.')
                        continue

                if errores:
                    messages.error(request, 'No se pudo finalizar: ' + ' '.join(errores))
                    return redirect('detalle_tarea', tarea_id=tarea.id)

                for mt, usado in consumos_tarea:
                    mt.stockusado = usado
                    mt.save(update_fields=['stockusado'])

                for material_id, total_usado in consumo_por_material.items():
                    mat = Material.objects.select_for_update().get(id=material_id)
                    reservado_tarea = int(reserva_por_material.get(material_id, 0))
                    nuevo_reservado = int(mat.stockreservado or 0) - reservado_tarea
                    mat.stockreservado = max(nuevo_reservado, 0)
                    mat.stockActual = int(mat.stockActual or 0) - total_usado
                    mat.save(update_fields=['stockreservado', 'stockActual'])

                tarea.estado = 'terminada'
                tarea.save(update_fields=['estado'])
                Notificacion.objects.filter(tarea=tarea, resolved=False).update(resolved=True)

                # MAGIA: Le avisamos al pedido y vemos qué pasa
                sincronizar_estado_pedido(tarea.pedido)

            messages.success(request, 'Tarea finalizada y stock actualizado.')
            
            # Verificamos cómo quedó el pedido después de sincronizar
            if tarea.pedido.estado == 'terminado':
                messages.success(request, 'Todas las tareas finalizaron. El pedido pasó a terminado.')
                
            return redirect('detalle_tarea', tarea_id=tarea.id)
        elif accion == 'agregarmaterialtarea':

            if tarea.estado not in ('revisada', 'por reparar') or tarea.pedido.estado not in ('revisado', 'por reparar'):

                messages.error(request, 'Solo puedes definir materiales cuando el pedido esta en revision o reparacion.')

                return redirect('detalle_tarea', tarea_id=tarea.id)



            if (tarea.tipoTarea or '').strip() == 'control':

                messages.error(request, 'Una tarea de control no necesita materiales.')

                return redirect('detalle_tarea', tarea_id=tarea.id)



            material_ids = request.POST.getlist('material_id[]')

            cantidades = request.POST.getlist('cantidadrecomendada[]')

            mapa_recomendados = {

                str(item.material_id): int(item.cantidadrecomendada or 0)

                for item in MaterialFichaAmortiguador.objects.filter(fichaamortiguador=tarea.amortiguador.fichaamortiguador)

            }



            materiales_para_guardar = []

            hubo_material_valido = False

            for material_id, cantidad in zip(material_ids, cantidades):

                try:

                    if material_id not in mapa_recomendados:

                        messages.error(request, 'Se detecto un material invalido para esta ficha tecnica.')

                        return redirect('detalle_tarea', tarea_id=tarea.id)



                    material = Material.objects.get(id=material_id)

                    cantidad_int = int(cantidad)

                    if cantidad_int < 0:

                        messages.error(request, f'Cantidad invalida para {material.tipo}. No puede ser negativa.')

                        return redirect('detalle_tarea', tarea_id=tarea.id)



                    max_recomendado = int(mapa_recomendados.get(material_id, 0))

                    if cantidad_int > max_recomendado:

                        messages.error(

                            request,

                            f'Cantidad invalida para {material.tipo}. El maximo para esta ficha es {max_recomendado}.'

                        )

                        return redirect('detalle_tarea', tarea_id=tarea.id)



                    if cantidad_int >= 1:

                        hubo_material_valido = True

                        materiales_para_guardar.append((material, cantidad_int))

                except (Material.DoesNotExist, ValueError):

                    messages.error(request, 'Hay cantidades invalidas. Revisa los valores ingresados.')

                    return redirect('detalle_tarea', tarea_id=tarea.id)



            if not hubo_material_valido:

                messages.error(request, 'Debes asignar al menos un material con cantidad mayor a 0.')

                return redirect('detalle_tarea', tarea_id=tarea.id)



            MaterialTarea.objects.filter(tarea=tarea).delete()

            for material, cantidad_int in materiales_para_guardar:

                MaterialTarea.objects.create(

                    tarea=tarea,

                    material=material,

                    stockrecomendado=cantidad_int,

                )



            messages.success(request, 'Materiales maximos guardados correctamente para la tarea.')

            return redirect('detalle_pedido', pedido_id=tarea.pedido.id)
            
    user_role = context.get('user_role')
    template_name = 'detalle_tarea_operario.html' if user_role == 'operario' else 'detalle_tarea_encargado.html'
    return render(request, template_name, context)


@role_required(['operario'])
def crear_o_editar_observacion(request, tarea_id):
    tarea = get_object_or_404(Tarea, id=tarea_id)
    if tarea.estado != 'pendiente':
        messages.error(request, 'La tarea no está en estado pendiente.')
        return redirect('detalle_tarea', tarea_id=tarea.id)

    if request.method == 'POST':
        sugerencia = request.POST.get('sugerencia_tipo')
        valor_diag = request.POST.get('valordiagrama')
        comentario_operario = request.POST.get('detalle_operario', '') # <-- Nuevo campo manual
        
        # 1. Iniciamos el texto autogenerado
        texto_sistema = f"SUGERENCIA TÉCNICA: {sugerencia.upper()}\n"
        
        # 2. Manejo de materiales y concatenación
        MaterialTarea.objects.filter(tarea=tarea).delete()
        if sugerencia == 'reparacion':
            texto_sistema += "Materiales sugeridos:\n"
            material_ids = request.POST.getlist('material_id[]')
            cantidades = request.POST.getlist('cantidadrecomendada[]')
            
            for m_id, cant in zip(material_ids, cantidades):
                cantidad_int = int(cant)
                if cantidad_int > 0:
                    material_obj = Material.objects.get(id=m_id)
                    texto_sistema += f" - {material_obj.tipo}: {cantidad_int}\n"
                    MaterialTarea.objects.create(tarea=tarea, material=material_obj, stockrecomendado=cantidad_int)
            tarea.tipoTarea = 'reparacion'
        else:
            texto_sistema += "No requiere materiales adicionales.\n"
            tarea.tipoTarea = 'control'
        
        # 3. Guardar modelo unificado
        obs, _ = Observacion.objects.update_or_create(
            tarea=tarea,
            defaults={
                'amortiguador': tarea.amortiguador,
                'sugerencia_tecnica': sugerencia,
                'valor_diagrama': valor_diag,
                'detalle_operario': comentario_operario,     # Lo que escribió el operario
                'detalle_autogenerado': texto_sistema        # Lo que armó el sistema
            }
        )
        
        tarea.save()
        messages.success(request, 'Diagnóstico completo guardado.')
        return redirect('detalle_tarea', tarea_id=tarea.id)

    context = {
        'tarea': tarea,
        'materiales_sugeribles': _materiales_para_sugerencia_tarea(tarea),
        'ficha': tarea.amortiguador.fichaamortiguador,
        'obs': getattr(tarea, 'observacion', None)
    }
    return render(request, 'form_observacion_unica.html', context)






def listapedidos(request):
    # Estados exactos solicitados
    estados_validos = ['en curso', 'revisado', 'terminado', 'aprobado', 'retirado']
    
    pedidos = Pedido.objects.all().order_by('-id')

    # 1. Buscador Unificado (ID o DNI)
    query = request.GET.get('q', '').strip()
    if query:
        # Filtramos: El ID contiene el texto O el DNI del cliente contiene el texto
        pedidos = pedidos.filter(
            Q(id__icontains=query) | Q(cliente__dni__icontains=query)
        )

    # 2. Filtro por Estado
    estado_filtro = request.GET.get('estado')
    if estado_filtro and estado_filtro in estados_validos:
        pedidos = pedidos.filter(estado=estado_filtro)

    context = {
        'pedidos': pedidos,
        'estados_disponibles': estados_validos,
        'query': query,
        'estado_seleccionado': estado_filtro
    }
    return render(request, 'listapedidos.html', context)

@role_required(['encargado'])
def panel_notificaciones(request):
    desde = (request.GET.get('desde') or '').strip()
    hasta = (request.GET.get('hasta') or '').strip()
    estado_notif = (request.GET.get('estado_notif') or 'activas').strip().lower()
    if estado_notif not in ('activas', 'resueltas', 'todas'):
        estado_notif = 'activas'

    notificaciones = Notificacion.objects.select_related(
        'tarea',
        'tarea__pedido',
        'tarea__amortiguador',
    ).order_by('-fecha_solicitud')

    if estado_notif == 'activas':
        notificaciones = notificaciones.filter(resolved=False)
    elif estado_notif == 'resueltas':
        notificaciones = notificaciones.filter(resolved=True)

    if desde:
        notificaciones = notificaciones.filter(fecha_solicitud__date__gte=desde)
    if hasta:
        notificaciones = notificaciones.filter(fecha_solicitud__date__lte=hasta)

    filas_reporte = {}
    notificaciones_detalle = []

    for notif in notificaciones:
        try:
            materiales = json.loads(notif.materiales or '[]')
        except json.JSONDecodeError:
            materiales = []

        materiales_legibles = []
        for item in materiales:
            nombre = item.get('material') or 'Material sin nombre'
            requerido = int(item.get('requerido') or 0)
            disponible = int(item.get('disponible') or 0)
            faltante = max(requerido - disponible, 0)

            materiales_legibles.append(f"{nombre} (req: {requerido}, disp: {disponible})")

            if nombre not in filas_reporte:
                filas_reporte[nombre] = {
                    'material': nombre,
                    'veces_sin_stock': 0,
                    'faltante_total': 0,
                }

            filas_reporte[nombre]['veces_sin_stock'] += 1
            filas_reporte[nombre]['faltante_total'] += faltante

        notificaciones_detalle.append({
            'id': notif.id,
            'fecha_solicitud': notif.fecha_solicitud,
            'tarea_id': notif.tarea_id,
            'pedido_id': notif.tarea.pedido_id,
            'resolved': notif.resolved,
            'materiales': materiales_legibles,
        })

    reporte_materiales = sorted(
        filas_reporte.values(),
        key=lambda x: (-x['veces_sin_stock'], x['material'])
    )

    materiales_bajo_minimo = []
    for material in Material.objects.all().order_by('tipo'):
        stock_actual = int(material.stockActual or 0)
        stock_minimo = int(material.stockMinimo or 0)
        stock_reservado = int(material.stockreservado or 0)
        stock_disponible = stock_actual - stock_reservado

        if stock_actual < stock_minimo:
            materiales_bajo_minimo.append({
                'id': material.id,
                'material': material.tipo,
                'stock_actual': stock_actual,
                'stock_minimo': stock_minimo,
                'stock_reservado': stock_reservado,
                'stock_disponible': stock_disponible,
            })

    context = {
        'notificaciones': notificaciones_detalle,
        'reporte_materiales': reporte_materiales,
        'materiales_bajo_minimo': materiales_bajo_minimo,
        'desde': desde,
        'hasta': hasta,
        'estado_notif': estado_notif,
    }
    return render(request, 'panel_notificaciones.html', context)



@role_required(['operario', 'encargado'])
def historial_amortiguador(request, tarea_id):
    # 1. Obtenemos la tarea y de ahí sacamos el amortiguador
    tarea = get_object_or_404(Tarea, id=tarea_id)
    amortiguador = tarea.amortiguador
    
    # 2. Filtramos las observaciones unificadas y ordenamos por el nuevo campo 'fecha'
    observaciones = Observacion.objects.filter(amortiguador=amortiguador).order_by('-fecha')
    
    # 3. Mantenemos exactamente tu mismo contexto
    context = {
        'amortiguador': amortiguador, 
        'observaciones': observaciones, 
        'id_pedido': tarea.pedido.id
    }
    
    return render(request, 'historial_amortiguador.html', context)
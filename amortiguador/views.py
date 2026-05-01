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
from decimal import Decimal

PRECIO_REVISION_BASE = Decimal('20000.00') # Define un costo base para la revisión


from .models import Cliente , Pedido, Operario, Amortiguador, Fichaamortiguador, Tarea, Observacion, Material, MaterialFichaAmortiguador, MaterialTarea, Notificacion


def _get_request_role(request):
    operario = getattr(request.user, 'operario', None)
    if operario:
        return operario.role
    if getattr(request.user, 'is_superuser', False):
        return 'encargado'
    return None


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
        f"Estado: {pedido.estado}",
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
    
    presupuesto_estimado = 0
    if pedido.estado == 'revisado':
        presupuesto_estimado = _obtener_presupuesto_estimado(pedido)


    if request.method == 'POST':
        accion = request.POST.get('accion')
        if accion == 'terminar_revision_pedido':
            # Validar que todas las tareas tengan tipo definido
            tareas_sin_tipo = tareas.filter(tipoTarea__isnull=True) | tareas.filter(tipoTarea='')
            if tareas_sin_tipo.exists():
                messages.error(request, 'No puedes terminar la revisión si hay tareas sin tipo definido.')
                return redirect('detalle_pedido', pedido_id=pedido.id)
            
            # Cambiar estado según si hay tareas de reparación
            tareas_reparacion = tareas.filter(tipoTarea='reparacion')
            if tareas_reparacion.exists():
                pedido.estado = 'revisado' # Cambiado a 'revisado' para el presupuesto
                messages.success(request, 'Revisión completada. Ahora puedes generar y enviar el presupuesto.')
            else:
                # Si todas son control, el pedido está terminado
                pedido.estado = 'terminado'
                messages.success(request, '¡El pedido ha sido finalizado como control, avisale al cliente!')
            
            pedido.save()
            return redirect('detalle_pedido', pedido_id=pedido.id)
        elif accion == 'crear_tarea':
            return redirect('create_tarea', pedido_id=pedido.id)
        elif accion == 'aprobar_presupuesto':
            if pedido.estado == 'revisado':
                # 1. Calcular y guardar el total definitivo aceptado
                total = _obtener_presupuesto_estimado(pedido)
                pedido.total_estimado = total
                pedido.estado = 'por reparar'
                pedido.save()
                
                # 2. Lógica de Reserva (Resta Imaginaria)
                # Iteramos sobre los materiales sugeridos para reservarlos
                for tarea in tareas.filter(tipoTarea='reparacion'):
                    for mt in tarea.materialtarea_set.all():
                        material = mt.material
                        # Restamos del stock real para moverlo a reservado
                        material.stockActual -= mt.stockrecomendado
                        material.save()
                
                messages.success(request, f'Presupuesto de ${total} aprobado. Materiales reservados.')
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
            if pedido.estado != 'terminado':
                messages.error(request, 'Solo los pedidos terminados pueden pasar a listo para retirar.')
                return redirect('detalle_pedido', pedido_id=pedido.id)

            pedido.estado = 'listo para retirar'
            pedido.save(update_fields=['estado'])
            messages.success(request, 'Pedido marcado como listo para retirar.')
            return redirect('detalle_pedido', pedido_id=pedido.id)
        elif accion == 'emitir_comprobante':
            if pedido.estado not in ('terminado', 'listo para retirar'):
                messages.error(request, 'El comprobante solo se puede emitir para pedidos terminados o listos para retirar.')
                return redirect('detalle_pedido', pedido_id=pedido.id)

            pdf_bytes = _generar_comprobante_pdf(pedido, tareas)
            response = HttpResponse(pdf_bytes, content_type='application/pdf')
            response['Content-Disposition'] = f'attachment; filename="comprobante_pedido_{pedido.id}.pdf"'
            return response
        elif accion == 'enviar_comprobante':
            if pedido.estado not in ('terminado', 'listo para retirar'):
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

    context = {
        'pedido': pedido,
        'tareas': tareas,
        'mensaje_exito': mensaje_exito,
        'editar_plan': editar_plan,
        'tareas_reparacion_editables': tareas_reparacion_editables,
        'presupuesto_estimado': presupuesto_estimado,
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
    tarea= get_object_or_404(Tarea, id=tarea_id)
    if not _can_access_tarea(request, tarea):
        return HttpResponseForbidden('No tienes permisos para ver esta tarea.')

    context = {'tarea': tarea, 'user_role': _get_request_role(request)}
    observaciones = Observacion.objects.filter(tarea=tarea)
    context['observaciones'] = observaciones
    materialxamortiguador = MaterialFichaAmortiguador.objects.filter(fichaamortiguador=tarea.amortiguador.fichaamortiguador)
    materialxtarea = MaterialTarea.objects.filter(tarea=tarea)
    context['materialxtarea'] = materialxtarea
    context['materialxamortiguador'] = materialxamortiguador
    context['materiales_sugeribles'] = _materiales_para_sugerencia_tarea(tarea)
    context['observacion_fisica'] = _observacion_para_tarea(tarea, 'controlfisico')
    context['observacion_diagrama'] = _observacion_para_tarea(tarea, 'controldiagrama')
    
    # Extraer sugerencia de tipo de las observaciones
    tipo_sugerido = None
    obs_fisica = _observacion_para_tarea(tarea, 'controlfisico')
    if obs_fisica and obs_fisica.infoobservacion:
        if 'Sugerencia tecnica: control' in obs_fisica.infoobservacion:
            tipo_sugerido = 'control'
        elif 'Sugerencia tecnica: reparacion' in obs_fisica.infoobservacion:
            tipo_sugerido = 'reparacion'
    context['tipo_sugerido'] = tipo_sugerido
    if request.method == 'POST':
        accion = request.POST.get('accion')
        if not _can_perform_tarea_action(request, tarea, accion):
            return HttpResponseForbidden('No tienes permisos para realizar esta acción.')

        if accion == 'terminarobservacioncontrol':
            if tarea.estado != 'pendiente':
                messages.error(request, 'Solo puedes cerrar observaciones cuando la tarea esta pendiente.')
                return redirect('detalle_tarea', tarea_id=tarea.id)

            if not observaciones.exists():
                messages.error(request, 'Debes cargar al menos una observacion antes de cerrar la revision.')
                return redirect('detalle_tarea', tarea_id=tarea.id)

            tarea.estado = 'revisada'
            tarea.save()
            context['class'] = 'alert alert-success'
            context['message'] = 'Has finalizado las observaciones de control de calidad.'
            tareas = Tarea.objects.filter(pedido= tarea.pedido)
            if all(t.estado == 'revisada' for t in tareas):
                pedido = tarea.pedido
                pedido.estado = 'revisado'
                pedido.save()
            return redirect('home')
        elif accion == 'guardar_tipo_materiales':
            # Encargado guarda tipo y materiales a la vez
            if tarea.estado not in ('revisada', 'por reparar'):
                messages.error(request, 'Solo puedes guardar tipo y materiales cuando la tarea esta en revision o por reparar.')
                return redirect('detalle_tarea', tarea_id=tarea.id)

            nuevo_tipo = (request.POST.get('tipoTarea') or '').strip()
            if nuevo_tipo not in ('control', 'reparacion'):
                messages.error(request, 'Tipo invalido.')
                return redirect('detalle_tarea', tarea_id=tarea.id)

            # parse materials
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

            # If selecting reparacion, require at least one material
            if nuevo_tipo == 'reparacion' and not materiales_para_guardar:
                messages.error(request, 'Debes aprobar al menos un material para reparación.')
                return redirect('detalle_tarea', tarea_id=tarea.id)

            tipo_actual = (tarea.tipoTarea or '').strip()
            cambio_de_tipo = tipo_actual != nuevo_tipo

            with transaction.atomic():
                # Apply type change
                tarea.tipoTarea = nuevo_tipo
                tarea.estado = 'por reparar' if nuevo_tipo == 'reparacion' else 'revisada'
                tarea.save(update_fields=['tipoTarea', 'estado'])

                # Replace materials according to form
                if nuevo_tipo == 'control':
                    MaterialTarea.objects.filter(tarea=tarea).delete()
                else:
                    MaterialTarea.objects.filter(tarea=tarea).delete()
                    for material, cantidad_int in materiales_para_guardar:
                        MaterialTarea.objects.create(
                            tarea=tarea,
                            material=material,
                            stockrecomendado=cantidad_int,
                        )

            if cambio_de_tipo:
                messages.success(request, 'Tipo y materiales guardados correctamente.')
            else:
                messages.success(request, 'Materiales actualizados correctamente.')
            return redirect('detalle_tarea', tarea_id=tarea.id)
        elif accion == 'confirmarreparacion':
            if tarea.estado not in ('revisada', 'por reparar'):
                messages.error(request, 'Solo puedes cambiar el tipo cuando la tarea esta revisada o por reparar.')
                return redirect('detalle_tarea', tarea_id=tarea.id)

            nuevo_tipo = request.POST.get('confirmarreparacion')
            if nuevo_tipo not in ('control', 'reparacion'):
                messages.error(request, 'Tipo de tarea invalido.')
                return redirect('detalle_tarea', tarea_id=tarea.id)

            tipo_actual = (tarea.tipoTarea or '').strip()
            cambio_de_tipo = tipo_actual != nuevo_tipo

            if nuevo_tipo == 'control' and MaterialTarea.objects.filter(tarea=tarea).exists():
                # Al pasar a control, se limpian materiales para evitar inconsistencias.
                MaterialTarea.objects.filter(tarea=tarea).delete()

            if nuevo_tipo == 'control':
                tarea.tipoTarea = 'control'
                tarea.estado = 'revisada'
                tarea.save(update_fields=['tipoTarea', 'estado'])
                if cambio_de_tipo:
                    messages.warning(request, 'Se cambio la tarea a control y se eliminaron los materiales planificados.')
                else:
                    messages.success(request, 'La tarea quedo confirmada como control.')
                return redirect('detalle_tarea', tarea_id=tarea.id)

            tarea.tipoTarea = 'reparacion'
            tarea.estado = 'por reparar'
            tarea.save(update_fields=['tipoTarea', 'estado'])
            if cambio_de_tipo:
                messages.warning(request, 'Se cambio la tarea a reparacion y se mantuvieron o ajustaron los materiales sugeridos.')
            else:
                messages.success(request, 'La tarea quedo confirmada como reparacion.')
            return redirect('detalle_tarea', tarea_id=tarea.id)
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

            messages.success(request, 'Materiales reservados correctamente.')
            return redirect('detalle_tarea', tarea_id=tarea.id)
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

                pedido = tarea.pedido
                pedido_terminado = _actualizar_estado_pedido_si_corresponde(pedido)

            messages.success(request, 'Tarea finalizada y stock actualizado.')
            if pedido_terminado:
                messages.success(request, 'Todas las tareas finalizaron. El pedido paso a terminado.')
            return redirect('detalle_pedido', pedido_id=tarea.pedido.id)

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
def create_observacion(request, tarea_id):
    tarea = get_object_or_404(Tarea, id=tarea_id)
    if not _can_access_tarea(request, tarea):
        return HttpResponseForbidden('No tienes permisos para crear observaciones en esta tarea.')

    if tarea.estado != 'pendiente':
        messages.error(request, 'Solo puedes modificar observaciones cuando la tarea esta pendiente.')
        return redirect('detalle_tarea', tarea_id=tarea.id)

    tipo_preseleccionado = (request.GET.get('tipo') or request.POST.get('tipoobservacion') or '').strip()
    observacion_existente = None
    if tipo_preseleccionado in ('controlfisico', 'controldiagrama'):
        observacion_existente = _observacion_para_tarea(tarea, tipo_preseleccionado)

    context = {
        'tarea': tarea,
        'user_role': _get_request_role(request),
        'tipo_preseleccionado': tipo_preseleccionado,
        'observacion_existente': observacion_existente,
    }
    context['materiales_sugeribles'] = _materiales_para_sugerencia_tarea(tarea)
    if request.method == 'POST':
        accion = request.POST.get('accion')
        if accion == 'observacion_control_calidad':
            tarea = get_object_or_404(Tarea, id=request.POST.get('tarea_id'))
            tipoobservacion = request.POST.get('tipoobservacion')
            if tipoobservacion not in ('controlfisico', 'controldiagrama'):
                messages.error(request, 'Tipo de observacion invalido.')
                return redirect('create_observacion', tarea_id=tarea.id)

            sugerencia_tipo = (request.POST.get('sugerencia_tipo') or '').strip()
            if tipoobservacion != 'controlfisico':
                sugerencia_tipo = ''
            if sugerencia_tipo and sugerencia_tipo not in ('control', 'reparacion'):
                messages.error(request, 'La sugerencia tecnica es invalida.')
                return redirect('create_observacion', tarea_id=tarea.id)

            material_ids = request.POST.getlist('material_id[]') if sugerencia_tipo else []
            cantidades = request.POST.getlist('cantidadrecomendada[]') if sugerencia_tipo else []
            materiales_ficha = {
                str(item.material_id): int(item.cantidadrecomendada or 0)
                for item in MaterialFichaAmortiguador.objects.filter(fichaamortiguador=tarea.amortiguador.fichaamortiguador)
            }

            materiales_sugeridos = []
            for material_id, cantidad_raw in zip(material_ids, cantidades):
                if material_id not in materiales_ficha:
                    messages.error(request, 'Se detecto un material invalido para esta ficha tecnica.')
                    return redirect('create_observacion', tarea_id=tarea.id)

                try:
                    cantidad_int = int(cantidad_raw)
                except (TypeError, ValueError):
                    messages.error(request, 'Hay cantidades invalidas en la sugerencia de materiales.')
                    return redirect('create_observacion', tarea_id=tarea.id)

                if cantidad_int < 0:
                    messages.error(request, 'La cantidad sugerida no puede ser negativa.')
                    return redirect('create_observacion', tarea_id=tarea.id)

                maximo = materiales_ficha[material_id]
                if cantidad_int > maximo:
                    messages.error(request, f'La cantidad sugerida para el material supera el maximo de la ficha ({maximo}).')
                    return redirect('create_observacion', tarea_id=tarea.id)

                if cantidad_int > 0:
                    materiales_sugeridos.append((int(material_id), cantidad_int))

            if sugerencia_tipo == 'control' and materiales_sugeridos:
                messages.error(request, 'Si sugieres control, no debes cargar materiales.')
                return redirect('create_observacion', tarea_id=tarea.id)

            if sugerencia_tipo == 'reparacion' and not materiales_sugeridos:
                messages.error(request, 'Si sugieres reparacion, debes cargar al menos un material.')
                return redirect('create_observacion', tarea_id=tarea.id)

            obs_data = {
                'tarea': tarea,
                'amortiguador': tarea.amortiguador,
                'tipoobservacion': tipoobservacion,
                'infoobservacion': request.POST.get('infoobservacion'),
                'fechaobservacion': datetime.date.today(),
                'horaobservacion': datetime.datetime.now().time(),
            }
            if tipoobservacion == 'controldiagrama':
                obs_data['valordiagrama'] = request.POST.get('valordiagrama')

            if sugerencia_tipo:
                sugerencia_texto = f'Sugerencia tecnica: {sugerencia_tipo}'
                if obs_data.get('infoobservacion'):
                    obs_data['infoobservacion'] = f"{sugerencia_texto}\n{obs_data['infoobservacion']}"
                else:
                    obs_data['infoobservacion'] = sugerencia_texto

            Observacion.objects.update_or_create(
                tarea=tarea,
                tipoobservacion=tipoobservacion,
                defaults={
                    'amortiguador': tarea.amortiguador,
                    'infoobservacion': obs_data.get('infoobservacion'),
                    'valordiagrama': obs_data.get('valordiagrama'),
                },
            )

            if materiales_sugeridos:
                MaterialTarea.objects.filter(tarea=tarea).delete()
                for material_id, cantidad_int in materiales_sugeridos:
                    MaterialTarea.objects.create(
                        tarea=tarea,
                        material_id=material_id,
                        stockrecomendado=cantidad_int,
                    )

            messages.success(request, 'Observacion y sugerencia tecnica guardadas correctamente.')
            return redirect('detalle_tarea', tarea_id=tarea.id)

    return render(request, 'create_observacion.html', context)

@role_required(['encargado'])
def listapedidosrevisados(request):
    estado_seleccionado = (request.GET.get('estado') or '').strip()
    dni_buscado = (request.GET.get('dni') or '').strip()
    solo_listos_dni = (request.GET.get('solo_listos_dni') or '').strip() == '1'

    pedidos = Pedido.objects.select_related('cliente').all().order_by('-id')
    estados_disponibles = (
        'revisado', 'terminado', 'listo para retirar', 'por reparar'
    )

    if estado_seleccionado:
        pedidos = pedidos.filter(estado=estado_seleccionado)

    if dni_buscado:
        pedidos = pedidos.filter(cliente__dni__icontains=dni_buscado)
        if solo_listos_dni:
            pedidos = pedidos.filter(estado='listo para retirar')

    context = {
        'pedidos': pedidos,
        'estados_disponibles': estados_disponibles,
        'estado_seleccionado': estado_seleccionado,
        'dni_buscado': dni_buscado,
        'solo_listos_dni': solo_listos_dni,
    }
    return render(request, 'listapedidosrevisados.html', context)


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

def historial_amortiguador(request, tarea_id):

    tarea = get_object_or_404(Tarea, id=tarea_id)
    amortiguador = tarea.amortiguador
    observaciones = Observacion.objects.filter(amortiguador=amortiguador).order_by('-fechaobservacion', '-horaobservacion')
    return render(request, 'historial_amortiguador.html', {'amortiguador': amortiguador, 'observaciones': observaciones, 'id_pedido': tarea.pedido.id})


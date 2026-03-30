import datetime
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse
from django.contrib.auth.decorators import login_required
from .decorators import role_required

from .models import Cliente , Pedido, Operario, Amortiguador, Fichaamortiguador, Tarea, Observacion, Material, MaterialFichaAmortiguador, MaterialTarea, Notificacion
def home(request):
    return render(request, 'home.html')

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
    
def detalle_pedido(request, pedido_id):
    pedido = get_object_or_404(Pedido, id=pedido_id)
    tareas = Tarea.objects.filter(pedido=pedido)
    
    
    mensaje_exito = None
    if tareas.exists() and all(t.estado in ['terminada', 'por reparar'] for t in tareas):
        mensaje_exito = '¡Todas las tareas están finalizadas o por reparar!'
        pedido.estado = 'por reparar'
        pedido.save()
    if tareas.exists() and all(t.estado in 'terminada' for t in tareas):
        pedido.estado = 'terminado'
        pedido.save()
        mensaje_exito = '¡El pedido ha sido finalizado, avisale al cliente!'
    if request.method == 'POST':
        accion = request.POST.get('accion')
        if accion == 'crear_tarea':
            return redirect('create_tarea', pedido_id=pedido.id)
        elif accion == 'finalizar_pedido':
            fecha_limite = request.POST.get('fecha_limite')
            try:
                for tarea in tareas:
                    tarea.fechaLimite = fecha_limite
                    tarea.save()
                pedido.fechaSalidaEstimada = fecha_limite
                pedido.save()
                return redirect('home')

            except ValueError:
                mensaje_exito = 'Fecha inválida. Por favor, ingrese una fecha válida.'

    return render(request, 'detalle_pedido.html', {'pedido': pedido, 'tareas': tareas, 'mensaje_exito': mensaje_exito})


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
            context['tareas'] = tareas
            context['operario'] = operario

            if estadoselect:
                context['titulo_tareas'] = f"Tareas con estado '{estadoselect}'"
            else:
                context['titulo_tareas'] = "Tareas Pendientes"

    if request.method == 'GET' and user_operario:
        tareas = Tarea.objects.filter(operario=user_operario, estado='por reparar')
        context['tareas'] = tareas
        context['titulo_tareas'] = "Tareas con estado 'por reparar'"
    return render(request, 'paneltareas.html', context)

def detalle_tarea(request, tarea_id):
    tarea= get_object_or_404(Tarea, id=tarea_id)
    context = {'tarea': tarea}
    observaciones = Observacion.objects.filter(tarea=tarea)
    context['observaciones'] = observaciones
    materialxamortiguador = MaterialFichaAmortiguador.objects.filter(fichaamortiguador=tarea.amortiguador.fichaamortiguador)
    materialxtarea = MaterialTarea.objects.filter(tarea=tarea)
    context['materialxtarea'] = materialxtarea
    context['materialxamortiguador'] = materialxamortiguador
    if request.method == 'POST':
        accion = request.POST.get('accion')
        if accion == 'terminarobservacioncontrol':
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
        elif accion == 'confirmarreparacion':
            confirmarreparacion = request.POST.get('confirmarreparacion')
            if confirmarreparacion == 'control':
                tarea.tipoTarea = 'control'
                tarea.estado = 'terminada'
                tarea.save()
                return redirect('detalle_pedido', pedido_id=tarea.pedido.id)
            elif confirmarreparacion == 'reparacion':
                tarea.tipoTarea = 'reparacion'
                tarea.estado = 'por reparar'
                tarea.save()
                # volver a la vista de detalle para recargar desde la base de datos
                return redirect('detalle_tarea', tarea_id=tarea.id)
        elif accion == 'reservar_materiales':
            for mt in materialxtarea:
                mat = mt.material
                incremento = int(mt.stockrecomendado or 0)
                mat.stockreservado = int(mat.stockreservado or 0) + incremento
                mat.save()
            tarea.estado = 'en reparacion'
            tarea.save()
            return redirect('home')

        elif accion == 'agregarmaterialtarea':
            material_ids = request.POST.getlist('material_id[]')
            cantidades = request.POST.getlist('cantidadrecomendada[]')
            for material_id, cantidad in zip(material_ids, cantidades):
                try:
                    material = Material.objects.get(id=material_id)
                    cantidad_int = int(cantidad)
                    if cantidad_int >= 1:
                        MaterialTarea.objects.create(
                            tarea=tarea,
                            material=material,
                            stockrecomendado=cantidad_int
                        )
                except (Material.DoesNotExist, ValueError):
                    continue
            return redirect('detalle_pedido', pedido_id=tarea.pedido.id)
            
    return render(request, 'detalle_tarea.html', context)


def create_observacion(request, tarea_id):
    tarea = get_object_or_404(Tarea, id=tarea_id)
    context = {'tarea': tarea}
    if request.method == 'POST':
        accion = request.POST.get('accion')
        if accion == 'observacion_control_calidad':
            tarea = get_object_or_404(Tarea, id=request.POST.get('tarea_id'))
            tipoobservacion = request.POST.get('tipoobservacion')
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
            Observacion.objects.create(**obs_data)

            return redirect('detalle_tarea', tarea_id=tarea.id)

    return render(request, 'create_observacion.html', context)

@role_required(['encargado'])
def listapedidosrevisados(request):
    pedidos = Pedido.objects.filter(estado='revisado')
    return render(request, 'listapedidosrevisados.html', {'pedidos': pedidos})

def historial_amortiguador(request, tarea_id):

    tarea = get_object_or_404(Tarea, id=tarea_id)
    amortiguador = tarea.amortiguador
    observaciones = Observacion.objects.filter(amortiguador=amortiguador).order_by('-fechaobservacion', '-horaobservacion')
    return render(request, 'historial_amortiguador.html', {'amortiguador': amortiguador, 'observaciones': observaciones, 'id_pedido': tarea.pedido.id})


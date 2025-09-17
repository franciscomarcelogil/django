import datetime
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse

from .models import Cliente , Pedido, Operario, Amortiguador, Fichaamortiguador, Tarea, Observacion, Material
def home(request):
    return render(request, 'home.html')

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
    if request.method == 'POST':
        accion = request.POST.get('accion')
        if accion == 'crear_tarea':
            return redirect('create_tarea', pedido_id=pedido.id)
    return render(request, 'detalle_pedido.html', {'pedido': pedido, 'tareas': tareas})


def create_tarea(request, pedido_id):
    operarios = Operario.objects.all()
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

def paneltareas(request):
    operarios = Operario.objects.all()
    context = { 'operarios': operarios }
    if request.method == 'POST':
        accion = request.POST.get('accion')
        if accion == 'elegiroperario':
            operario_id = request.POST.get('operario')
            operario = get_object_or_404(Operario, id=operario_id)
            tareas = Tarea.objects.filter(operario=operario, estado='pendiente')
            context['tareas'] = tareas
            context['operario'] = operario
    return render(request, 'paneltareas.html', context)

def detalle_tarea(request, tarea_id):
    tarea= get_object_or_404(Tarea, id=tarea_id)
    context = {'tarea': tarea}
    observaciones = Observacion.objects.filter(tarea=tarea)
    context['observaciones'] = observaciones
    if request.method == 'POST':
        accion = request.POST.get('accion')
        if accion == 'terminarobservacioncontrol':
            tarea.estado = 'revisada'
            tarea.save()
            context['class'] = 'alert alert-success'
            context['message'] = 'Has finalizado las observaciones de control de calidad.'
            return redirect('home')
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
            if tarea.amortiguador.fichaamortiguador.valor_minimo <= float(obs_data['valordiagrama']) <= tarea.amortiguador.fichaamortiguador.valor_maximo:
                context['class'] = 'alert alert-success'
                context['message'] = 'El valor del diagrama está dentro del rango aceptable.'
            else:
                context['class'] = 'alert alert-danger'
                context['message'] = 'El valor del diagrama está fuera del rango aceptable.'

            return render(request, 'create_observacion.html', context)

    return render(request, 'create_observacion.html', context)
import datetime
import json
from django.db import transaction
from django.db.models.functions import Coalesce
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse, HttpResponseForbidden, JsonResponse, request
from django.contrib.auth.decorators import login_required
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.contrib import messages
from django.conf import settings
from django.utils import timezone
from django.core.mail import EmailMessage
from .decorators import role_required
import openpyxl
from decimal import Decimal
from django.db.models import Q, F, Sum, Count
from django.db import models
from reportlab.lib.pagesizes import letter, A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from datetime import timedelta
import json



PRECIO_REVISION_BASE = Decimal('20000.00') 
MANO_OBRA_REPARACION = Decimal('40000.00')  




def _guardar_historico_precios_pedido(pedido, concepto='comprobante_emitido'):
    """Guarda snapshot del precio actual de todos los materiales usados en un pedido"""
    tareas = pedido.tarea_set.all()
    
    for tarea in tareas:
        for mat_tarea in tarea.materialtarea_set.all():
            material = mat_tarea.material
 
            HistoricoPrecioMaterial.objects.get_or_create(
                material=material,
                fecha_de_vigencia=timezone.now(),
                defaults={'precio_venta': material.precio_venta}
            )


def _obtener_precio_en_fecha(material, fecha_referencia):
    """
    Obtiene el precio de venta del material válido para una fecha específica.
    
    Busca el histórico de precios donde:
    - fecha_de_vigencia <= fecha_referencia
    - Selecciona el mayor (más reciente)
    
    Si no hay historico anterior o igual a esa fecha, retorna el precio actual.
    """
    if not fecha_referencia:
        return material.precio_venta
    
    historico = HistoricoPrecioMaterial.objects.filter(
        material=material,
        fecha_de_vigencia__lte=fecha_referencia
    ).order_by('-fecha_de_vigencia').first()
    
    if historico:
        return historico.precio_venta
    
    return material.precio_venta





from .models import Cliente , Pedido, Operario, Amortiguador, Fichaamortiguador, Tarea, Observacion, Material, MaterialFichaAmortiguador, MaterialTarea, Notificacion, Proveedor, Compra, Comprobante, HistoricoPrecioMaterial

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
            

            nombre_gen = sheet['B1'].value
            nro_serie = str(sheet['B2'].value) if sheet['B2'].value else ''
            
            if not nombre_gen or not nro_serie:
                messages.error(request, 'El Excel debe tener Nombre Genérico en B1 y Nro Serie en B2.')
                return redirect('lista_fichas')

            val_min = sheet['B3'].value or 0
            val_max = sheet['B4'].value or 0
            mano_obra = sheet['B5'].value or 0

 
            ficha, created = Fichaamortiguador.objects.get_or_create(
                nombregenerico=nombre_gen,
                nroseriegenerico=nro_serie,
                defaults={
                    'valor_minimo': val_min,
                    'valor_maximo': val_max,
                    'mano_obra_reparacion': mano_obra
                }
            )

         
            for row in sheet.iter_rows(min_row=8, values_only=True):
                nombre_mat = row[0]
                tipo_mat = row[1]
                unidad_mat = row[2] or 'unidad'
                cantidad_rec = row[3]
                
                if not nombre_mat: 
                    break 
                
        
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
    query = request.GET.get('q', '').strip()
    if query:
        materiales = Material.objects.filter(Q(nombre__icontains=query) | Q(tipo__icontains=query))
    else:
        materiales = Material.objects.all().order_by('nombre')

    return render(request, 'control_inventario.html', {'materiales': materiales, 'query': query})


def detalle_material(request, material_id):
    material = get_object_or_404(Material, id=material_id)
    historial_compras = Compra.objects.filter(material=material).order_by('-fecha_compra')
    historico_precios = material.historico_precios.all().order_by('-id')
    
    # NUEVA CONSULTA: Tareas terminadas que consumieron este material
    tareas_material = MaterialTarea.objects.filter(
        material=material,
        tarea__estado='terminada'
    ).select_related(
        'tarea', 'tarea__pedido', 'tarea__amortiguador', 'tarea__operario'
    ).order_by('-tarea__fecha_finalizacion', '-tarea__id')

    if request.method == 'POST':
        accion = request.POST.get('accion')

        if accion == 'editar_material':
            material.stockMinimo = int(request.POST.get('stock_minimo', material.stockMinimo))
            nuevo_precio = Decimal(request.POST.get('precio_venta', material.precio_venta).replace(',', '.'))
            
            if nuevo_precio != material.precio_venta:
                HistoricoPrecioMaterial.objects.create(
                    material=material,
                    precio_venta=nuevo_precio,
                    fecha_de_vigencia=timezone.now()
                )
            
            material.precio_venta = nuevo_precio
            material.save()
            messages.success(request, 'Datos del material actualizados.')
            return redirect('detalle_material', material_id=material.id)

        elif accion == 'cargar_compra':
            cuit_prov = request.POST.get('cuit_proveedor').strip()
            proveedor, created = Proveedor.objects.get_or_create(
                cuit=cuit_prov,
                defaults={
                    'nombre': request.POST.get('nombre_prov', 'Nuevo Proveedor'),
                    'telefono': request.POST.get('telefono_prov', '')
                }
            )

            cantidad_comprada = int(request.POST.get('cantidad', 0))
            costo_unitario_nuevo = Decimal(request.POST.get('costo_unitario').replace(',', '.'))

            nueva_compra = Compra.objects.create(
                material=material,
                proveedor=proveedor,
                cantidad=cantidad_comprada,
                costo_unitario=costo_unitario_nuevo
            )

            # --- CÁLCULO DE NUEVO COSTO (PPP) ---
            stock_actual = material.stockActual or 0
            costo_actual = material.costo_unidad or Decimal('0.00')

            valor_inventario_actual = Decimal(stock_actual) * costo_actual
            valor_nueva_compra = Decimal(cantidad_comprada) * costo_unitario_nuevo
            nuevo_stock = stock_actual + cantidad_comprada

            if nuevo_stock > 0:
                nuevo_costo_ppp = (valor_inventario_actual + valor_nueva_compra) / Decimal(nuevo_stock)
                material.costo_unidad = round(nuevo_costo_ppp, 2)
            else:
                material.costo_unidad = round(costo_unitario_nuevo, 2)

            # --- CAPTURAR MARGEN VISUAL Y APLICAR ---
            margen_str = request.POST.get('margen_aplicado', '0')
            try:
                margen_actual = Decimal(margen_str.replace(',', '.')) / Decimal('100.0')
            except (ValueError, TypeError, AttributeError):
                margen_actual = Decimal('0.00')

            nuevo_precio_venta = round(material.costo_unidad * (Decimal('1.00') + margen_actual), 2)

            # --- CREACIÓN FORZADA DEL HISTÓRICO Y AUTO-AJUSTE ---
            HistoricoPrecioMaterial.objects.create(
                material=material,
                precio_venta=nuevo_precio_venta,
                fecha_de_vigencia=timezone.now()
            )
            
            material.precio_venta = nuevo_precio_venta
            material.stockActual = nuevo_stock
            material.save()

            if created:
                messages.success(request, f'Proveedor registrado. Costo PPP: ${material.costo_unidad} | Nuevo Precio: ${material.precio_venta}')
            else:
                messages.success(request, f'Compra cargada. Costo PPP: ${material.costo_unidad} | Nuevo Precio: ${material.precio_venta}')

            return redirect('detalle_material', material_id=material.id)

    # Cálculo del margen para mostrar cuando se carga la página
    if material.costo_unidad and material.costo_unidad > 0:
        margen_actual = ((material.precio_venta - material.costo_unidad) / material.costo_unidad) * 100
    else:
        margen_actual = Decimal('0.00')

    return render(request, 'detalle_material.html', {
        'material': material, 
        'historial_compras': historial_compras,
        'historico_precios': historico_precios,
        'tareas_material': tareas_material,  # Se envía al contexto
        'margen_actual': round(margen_actual, 2)
    })
def buscar_proveedor_api(request):
    """Endpoint AJAX para buscar proveedor por CUIT"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Método no permitido'}, status=400)
    
    cuit = request.POST.get('cuit', '').strip()
    
    if not cuit:
        return JsonResponse({'error': 'CUIT vacío'}, status=400)
    
    try:
        proveedor = Proveedor.objects.get(cuit=cuit)
        return JsonResponse({
            'encontrado': True,
            'id': proveedor.id,
            'nombre': proveedor.nombre,
            'telefono': proveedor.telefono or '',
            'cuit': proveedor.cuit
        })
    except Proveedor.DoesNotExist:
        return JsonResponse({'encontrado': False})


def informe_stock_minimo(request):

    materiales_criticos = Material.objects.filter(stockActual__lt=F('stockMinimo'))
    
    reporte = []
    for m in materiales_criticos:
        proveedores_unicos = Proveedor.objects.filter(compra__material=m).distinct()
        
        datos_proveedores = []
        for p in proveedores_unicos:
  
            ultima_compra = Compra.objects.filter(material=m, proveedor=p).order_by('-fecha_compra').first()
            datos_proveedores.append({
                'nombre': p.nombre,
                'cuit': p.cuit,
                'telefono': p.telefono,
                'ultimo_precio': ultima_compra.costo_unitario if ultima_compra else 0,
                'fecha': ultima_compra.fecha_compra if ultima_compra else None
            })
            
        reporte.append({
            'material': m,
            'proveedores': datos_proveedores
        })

    return render(request, 'informe_stock.html', {'reporte': reporte})


def generar_pdf_stock(request):
    """Genera un PDF con el informe de stock bajo mínimo"""
    from io import BytesIO
    from datetime import datetime
    
    # Obtener datos del informe
    materiales_criticos = Material.objects.filter(stockActual__lt=F('stockMinimo'))
    
    reporte = []
    for m in materiales_criticos:
        proveedores_unicos = Proveedor.objects.filter(compra__material=m).distinct()
        
        datos_proveedores = []
        for p in proveedores_unicos:
            ultima_compra = Compra.objects.filter(material=m, proveedor=p).order_by('-fecha_compra').first()
            datos_proveedores.append({
                'nombre': p.nombre,
                'cuit': p.cuit or '—',
                'telefono': p.telefono or '—',
                'ultimo_precio': str(ultima_compra.costo_unitario) if ultima_compra else '0',
                'fecha': ultima_compra.fecha_compra.strftime('%d/%m/%Y') if ultima_compra else '—'
            })
            
        reporte.append({
            'material': m,
            'proveedores': datos_proveedores
        })
    
    # Crear buffer para PDF
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=0.5*inch, bottomMargin=0.5*inch)
    
    # Estilos
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=16,
        textColor=colors.HexColor('#2c3e50'),
        spaceAfter=6,
        fontName='Helvetica-Bold'
    )
    subtitle_style = ParagraphStyle(
        'CustomSubtitle',
        parent=styles['Normal'],
        fontSize=10,
        textColor=colors.HexColor('#7f8c8d'),
        spaceAfter=12
    )
    material_style = ParagraphStyle(
        'Material',
        parent=styles['Heading3'],
        fontSize=11,
        textColor=colors.HexColor('#2c3e50'),
        spaceAfter=6,
        fontName='Helvetica-Bold'
    )
    
    # Contenido
    story = []
    
    # Encabezado
    story.append(Paragraph("INFORME DE STOCK", title_style))
    story.append(Paragraph(f"Generado: {datetime.now().strftime('%d/%m/%Y %H:%M')}", subtitle_style))
    story.append(Spacer(1, 0.2*inch))
    
    if reporte:
        for item in reporte:
            material = item['material']
            
            # Título del material
            story.append(Paragraph(f"{material.nombre} ({material.tipo})", material_style))
            
            # Estado de stock
            stock_text = f"Stock actual: {material.stockActual} {material.unidad}s | Mínimo: {material.stockMinimo}"
            story.append(Paragraph(stock_text, ParagraphStyle(
                'StockInfo',
                parent=styles['Normal'],
                fontSize=9,
                textColor=colors.HexColor('#e74c3c'),
                spaceAfter=8
            )))
            
            # Tabla de proveedores
            if item['proveedores']:
                data = [
                    ['Proveedor', 'CUIT', 'Contacto', 'Última Compra', 'Precio'],
                    *[[
                        p['nombre'],
                        p['cuit'],
                        p['telefono'],
                        p['fecha'],
                        f"${p['ultimo_precio']}"
                    ] for p in item['proveedores']]
                ]
                
                table = Table(data, colWidths=[1.8*inch, 1.2*inch, 1.2*inch, 1.2*inch, 0.8*inch])
                table.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#ecf0f1')),
                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor('#34495e')),
                    ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                    ('ALIGN', (-1, 0), (-1, -1), 'RIGHT'),
                    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                    ('FONTSIZE', (0, 0), (-1, 0), 9),
                    ('FONTSIZE', (0, 1), (-1, -1), 8),
                    ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
                    ('TOPPADDING', (0, 0), (-1, 0), 8),
                    ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#ecf0f1')),
                    ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f9fafb')]),
                    ('TOPPADDING', (0, 1), (-1, -1), 4),
                    ('BOTTOMPADDING', (0, 1), (-1, -1), 4),
                ]))
                story.append(table)
            else:
                story.append(Paragraph("Sin proveedores registrados", ParagraphStyle(
                    'NoProviders',
                    parent=styles['Normal'],
                    fontSize=9,
                    textColor=colors.HexColor('#95a5a6'),
                    italic=True
                )))
            
            story.append(Spacer(1, 0.3*inch))
    else:
        story.append(Paragraph("No hay materiales por debajo del stock mínimo", ParagraphStyle(
            'NoData',
            parent=styles['Normal'],
            fontSize=11,
            textColor=colors.HexColor('#27ae60'),
            alignment=1
        )))
    

    doc.build(story)
    buffer.seek(0)
    

    response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="informe_stock_{datetime.now().strftime("%Y%m%d_%H%M%S")}.pdf"'
    
    return response


def detalle_ficha(request, ficha_id):
    ficha = get_object_or_404(Fichaamortiguador, id=ficha_id)
    materiales_ficha = MaterialFichaAmortiguador.objects.filter(fichaamortiguador=ficha)
    
    return render(request, 'detalle_ficha.html', {
        'ficha': ficha,
        'materiales_ficha': materiales_ficha
    })


@role_required(['encargado'])
def lista_operarios(request):
    from django.db.models import Count, Q, F, Sum
    from datetime import datetime, timedelta
    from decimal import Decimal
    from django.utils import timezone

    query = request.GET.get('q', '').strip()
    
    if query:
        operarios = Operario.objects.filter(
            Q(legajo__icontains=query) | 
            Q(nombre__icontains=query) | 
            Q(apellido__icontains=query)
        ).order_by('apellido', 'nombre')
    else:
        operarios = Operario.objects.all().order_by('apellido', 'nombre')

    fecha_hace_un_mes = timezone.now().date() - timedelta(days=30)

    operarios_con_tareas = []
    for op in operarios:
        if op.role == 'operario':
            tareas_pendientes = Tarea.objects.filter(operario=op, estado='pendiente').count()
            tareas_por_reparar = Tarea.objects.filter(operario=op, estado='por reparar').count()
            
            operarios_con_tareas.append({
                'operario': op,
                'tareas_pendientes': tareas_pendientes,
                'tareas_por_reparar': tareas_por_reparar,
                'total_tareas': tareas_pendientes + tareas_por_reparar
            })

    operarios_operario = operarios.filter(role='operario')
    operarios_encargado_materiales= operarios.filter(role='encargado_materiales')

    tareas_ultimo_mes = Tarea.objects.filter(
        fechaAsignacion__gte=fecha_hace_un_mes,
        operario__role='operario'
    )
    tareas_terminadas_mes = tareas_ultimo_mes.filter(estado='terminada').count()
    tareas_activas_mes = tareas_ultimo_mes.filter(estado__in=['pendiente', 'por reparar', 'en reparacion']).count()

    tareas_por_op_mes = []
    ingresos_por_op = []
    tiempos_por_op = [] # NUEVO: Lista para guardar los tiempos

    for op in operarios_operario:
        tareas_op = tareas_ultimo_mes.filter(operario=op)
        terminadas = tareas_op.filter(estado='terminada').count()
        activas = tareas_op.filter(estado__in=['pendiente', 'por reparar', 'en reparacion']).count()

        ingresos = Decimal('0.00')
        tiempos_minutos = [] # CAMBIO 1: Lo pasamos a minutos
        
        for tarea in tareas_op.filter(estado='terminada'):
            # Ingresos: Mano de obra
            ingresos += tarea.amortiguador.fichaamortiguador.mano_obra_reparacion
            
            # Ingresos: Materiales
            materiales_ingresos = tarea.materialtarea_set.all().aggregate(
                total=Sum(F('material__precio_venta') * F('stockrecomendado'), output_field=models.DecimalField())
            )['total'] or Decimal('0.00')
            ingresos += materiales_ingresos
            
            # CAMBIO 2: Cálculo de tiempos promedio SOLO para reparaciones
            if tarea.tipoTarea == 'reparacion' and getattr(tarea, 'fecha_inicio_reparacion', None) and getattr(tarea, 'fecha_finalizacion', None):
                try:
                    inicio = tarea.fecha_inicio_reparacion
                    fin = tarea.fecha_finalizacion
                    
                    # Truco de seguridad por si las fechas no tienen "timezone" o una es Date y la otra DateTime
                    import datetime as dt
                    if isinstance(inicio, dt.datetime) and isinstance(fin, dt.date) and not isinstance(fin, dt.datetime):
                        fin = dt.datetime.combine(fin, dt.time.min, tzinfo=inicio.tzinfo)
                    elif isinstance(fin, dt.datetime) and isinstance(inicio, dt.date) and not isinstance(inicio, dt.datetime):
                        inicio = dt.datetime.combine(inicio, dt.time.min, tzinfo=fin.tzinfo)

                    diferencia = fin - inicio
                    minutos = diferencia.total_seconds() / 60.0
                    
                    # CAMBIO 3: Si tardó menos de 1 minuto (por ser una prueba rápida), le clavamos 1 min.
                    if minutos < 1:
                        minutos = 1.0
                        
                    tiempos_minutos.append(minutos)
                except TypeError:
                    pass
        
        # Calcular promedio en minutos
        promedio_minutos = sum(tiempos_minutos) / len(tiempos_minutos) if tiempos_minutos else 0

        tareas_por_op_mes.append({
            'nombre': f"{op.nombre} {op.apellido}",
            'terminadas': terminadas,
            'activas': activas
        })
        ingresos_por_op.append({
            'nombre': f"{op.nombre} {op.apellido}",
            'ingresos': float(ingresos)
        })
        tiempos_por_op.append({
            'nombre': f"{op.nombre} {op.apellido}",
            'promedio_minutos': round(promedio_minutos, 1) # Lo mandamos como minutos
        })
    
    context = {
        'operarios_con_tareas': operarios_con_tareas,
        'query': query,
        'operarios': operarios,
        'operarios_encargado_materiales': operarios_encargado_materiales,
        'estadisticas': {
            'tareas_terminadas_mes': tareas_terminadas_mes,
            'tareas_activas_mes': tareas_activas_mes,
            'tareas_por_operario': tareas_por_op_mes,
            'ingresos_por_operario': ingresos_por_op,
            'tiempos_por_operario': tiempos_por_op # NUEVO: Agregado al contexto
        }
    }
    return render(request, 'lista_operarios.html', context)

def detalle_operario(request, operario_id):
    """Ver detalles del operario y sus tareas pendientes/por reparar"""
    operario = get_object_or_404(Operario, id=operario_id)
    

    tareas_pendientes = Tarea.objects.filter(operario=operario, estado='pendiente')
    tareas_por_reparar = Tarea.objects.filter(operario=operario, estado='por reparar')
    
    return render(request, 'detalle_operario.html', {
        'operario': operario,
        'tareas_pendientes': tareas_pendientes,
        'tareas_por_reparar': tareas_por_reparar
    })


def editar_operario(request, operario_id):
    """Editar datos del operario"""
    operario = get_object_or_404(Operario, id=operario_id)
    
    if request.method == 'POST':
        operario.nombre = request.POST.get('nombre', operario.nombre)
        operario.apellido = request.POST.get('apellido', operario.apellido)
        operario.estado = request.POST.get('estado', operario.estado)
        operario.save()
        
        messages.success(request, 'Datos del operario actualizados correctamente.')
        if operario.role == 'operario':
            return redirect('detalle_operario', operario_id=operario.id)
        else:
            return redirect('lista_operarios')
    
    return render(request, 'editar_operario.html', {'operario': operario})


def crear_operario(request):
    """Crear nuevo operario con usuario Django asociado"""
    if request.method == 'POST':
      
        username = request.POST.get('username', '').strip()
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')
        
   
        try:
            legajo = int(request.POST.get('legajo', ''))
        except ValueError:
            messages.error(request, 'El legajo debe ser un número.')
            return render(request, 'crear_operario.html')
        
        nombre = request.POST.get('nombre', '')
        apellido = request.POST.get('apellido', '')
        estado = request.POST.get('estado', 'activo')
        role = request.POST.get('role', 'operario')
        
 
        if not all([username, password, nombre, apellido]):
            messages.error(request, 'Todos los campos son requeridos.')
            return render(request, 'crear_operario.html')
        
        if User.objects.filter(username=username).exists():
            messages.error(request, 'El usuario ya existe.')
            return render(request, 'crear_operario.html')
        
        if Operario.objects.filter(legajo=legajo).exists():
            messages.error(request, 'El legajo ya existe.')
            return render(request, 'crear_operario.html')
        
        try:
        
            user = User.objects.create_user(
                username=username,
                email=email,
                password=password
            )
            
       
            operario = Operario.objects.create(
                legajo=legajo,
                nombre=nombre,
                apellido=apellido,
                estado=estado,
                password=password,
                user=user,
                role=role
            )
            
            messages.success(request, f'Operario {nombre} {apellido} creado correctamente.')
            return redirect('lista_operarios')
        
        except Exception as e:
            messages.error(request, f'Error al crear operario: {str(e)}')
            return render(request, 'crear_operario.html')
    
    return render(request, 'crear_operario.html')


@role_required(['encargado'])
def lista_clientes(request):
    """Listar todos los clientes con búsqueda por nombre o DNI"""
    query = request.GET.get('q', '').strip()
    
    if query:
        clientes = Cliente.objects.filter(
            Q(nombre__icontains=query) | 
            Q(apellido__icontains=query) | 
            Q(dni__icontains=query)
        ).order_by('apellido', 'nombre')
    else:
        clientes = Cliente.objects.all().order_by('apellido', 'nombre')
    
    context = {
        'clientes': clientes,
        'query': query
    }
    return render(request, 'lista_clientes.html', context)


@role_required(['encargado'])
def detalle_cliente(request, cliente_id):
    """Ver detalles del cliente y sus pedidos"""
    cliente = get_object_or_404(Cliente, id=cliente_id)
    pedidos = Pedido.objects.filter(cliente=cliente).order_by('-fechaingreso')
    
    if request.method == 'POST':
        accion = request.POST.get('accion')
        if accion == 'editar_cliente':
            cliente.nombre = request.POST.get('nombre', cliente.nombre)
            cliente.apellido = request.POST.get('apellido', cliente.apellido)
            cliente.telefono = request.POST.get('telefono', cliente.telefono)
            cliente.correo = request.POST.get('correo', cliente.correo)
            cliente.save()
            
            messages.success(request, 'Datos del cliente actualizados correctamente.')
            return redirect('detalle_cliente', cliente_id=cliente.id)
    
    context = {
        'cliente': cliente,
        'pedidos': pedidos
    }
    return render(request, 'detalle_cliente.html', context)


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

    # Si el pedido está "pendiente" es porque el encargado lo está armando.
    if pedido.estado == 'pendiente':
        return False

    estados = [t.estado for t in tareas]

    # 1. Si TODAS las tareas están pendientes
    if all(e == 'pendiente' for e in estados):
        nuevo_estado = 'asignado'
        
    # 2. Si hay AL MENOS UNA pendiente (pero no todas, ej: el operario empezó otra)
    elif any(e == 'pendiente' for e in estados):
        nuevo_estado = 'en curso'
        
    # 3. No hay pendientes. ¿Queda alguna por revisar por el encargado?
    elif any(e == 'no revisada' for e in estados):
        nuevo_estado = 'revisado'
        
    # 4. Si hay tareas "en reparación"
    elif any(e == 'en reparacion' for e in estados):
        nuevo_estado = 'aprobado' if pedido.estado in ['revisado', 'aprobado', 'presupuestado'] else pedido.estado
    elif pedido.fechaSalidaReal is not None: 
        nuevo_estado = 'retirado'
        
    # 5. REGLAS DE ORO DE PRESUPUESTO VS TERMINADO:
    elif all(e in ['por reparar', 'terminada'] for e in estados):
        
        if all(e == 'terminada' for e in estados):
            # Si el pedido ya avanzó, respetamos ese estado final y no lo retrocedemos
            if pedido.estado in ['notificado', 'retirado', 'cancelado', 'aprobado']:
                nuevo_estado = pedido.estado
            else:
                nuevo_estado = 'terminado' 
        else:
            # ¡ACÁ ESTÁ LA SOLUCIÓN!
            # Si ya fue aprobado por el cliente, no lo retrocedas a presupuestado
            if pedido.estado == 'aprobado':
                nuevo_estado = 'aprobado'
            else:
                nuevo_estado = 'presupuestado' 
            
    else:
        nuevo_estado = pedido.estado

    # Aplicamos el cambio si hubo mutación
    if pedido.estado != nuevo_estado:
        pedido.estado = nuevo_estado
        if nuevo_estado == 'terminado' and not pedido.fecha_finalizacion:
            pedido.fecha_finalizacion = timezone.now()
        if nuevo_estado == 'presupuestado' and not getattr(pedido, 'fecha_presupuesto', None):
            pedido.fecha_presupuesto = timezone.now()
        pedido.save(update_fields=['estado', 'fecha_finalizacion', 'fecha_presupuesto'])
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

    # ¡ACÁ ESTÁ EL ARREGLO! Agrupamos las acciones del encargado y agregamos 'devolver_tarea'
    acciones_encargado = [
        'confirmarreparacion', 
        'guardar_tipo_materiales', 
        'agregarmaterialtarea', 
        'eliminar_tarea',
        'devolver_tarea'  # <--- ESTO ES LO QUE FALTABA
    ]
    if accion in acciones_encargado:
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


    if (fecha_limite - hoy).days > 180:
        return None, 'La fecha limite no puede superar 180 dias desde hoy.'

    return fecha_limite, None


def _obtener_presupuesto_estimado(pedido):
    total_revision = Decimal(pedido.tarea_set.count()) * PRECIO_REVISION_BASE
    total_materiales = Decimal('0.00')
    total_mano_obra = Decimal('0.00')

    # Buscamos la fecha para congelar el precio en el presupuesto
    fecha_referencia = getattr(pedido, 'fecha_presupuesto', None) or getattr(pedido, 'fecha_finalizacion', None)

    for tarea in pedido.tarea_set.all():
        # ¡CORRECCIÓN CLAVE ACÁ!
        # Todo el cálculo de dinero extra (mano de obra y materiales)
        # DEBE ir adentro de este "if", así ignoramos los repuestos fantasma de los controles.
        if tarea.tipoTarea == 'reparacion':
            total_mano_obra += MANO_OBRA_REPARACION
            
            for mat_sugerido in tarea.materialtarea_set.all():
                precio_historico = _obtener_precio_en_fecha(mat_sugerido.material, fecha_referencia)
                total_materiales += (precio_historico * mat_sugerido.stockrecomendado)
            
    return total_revision + total_mano_obra + total_materiales

def _obtener_desglose_presupuesto(pedido):
    """
    Retorna un desglose detallado del presupuesto ESTIMADO.
    Busca los precios históricos de la 'fecha_presupuesto' para que no cambien por inflación.
    Si aún no hay fecha_presupuesto (ej: está en estado 'revisado'), usa los precios de HOY.
    """
    tareas = pedido.tarea_set.all()
    num_tareas = tareas.count()
    precio_revision_total = num_tareas * PRECIO_REVISION_BASE

    tareas_reparacion = tareas.filter(tipoTarea='reparacion')
    num_tareas_reparacion = tareas_reparacion.count()
    total_mano_obra_reparacion = num_tareas_reparacion * MANO_OBRA_REPARACION

    materiales_agrupados = {}
    
    # ¡NUEVA LÓGICA ACÁ! 
    # Busca la fecha en la que se generó el presupuesto. Si es None, usa HOY.
    fecha_referencia = getattr(pedido, 'fecha_presupuesto', None) or getattr(pedido, 'fecha_finalizacion', None) 

    for tarea in tareas_reparacion:
        for mat_sugerido in tarea.materialtarea_set.all():
            material = mat_sugerido.material
            # Buscamos el precio que tenía el material en ESA fecha_referencia
            precio_historico = _obtener_precio_en_fecha(material, fecha_referencia)
            material_id = material.id
            
            if material_id not in materiales_agrupados:
                materiales_agrupados[material_id] = {
                    'nombre': material.tipo, 
                    'precio_unitario': precio_historico,
                    'cantidad_total': Decimal('0'),
                }
            materiales_agrupados[material_id]['cantidad_total'] += mat_sugerido.stockrecomendado

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

    total_general = precio_revision_total + total_materiales + total_mano_obra_reparacion

    return {
        'num_tareas': num_tareas,
        'precio_revision_unitario': PRECIO_REVISION_BASE,
        'precio_revision_total': precio_revision_total,
        'num_tareas_reparacion': num_tareas_reparacion,
        'precio_mano_obra_unitario': MANO_OBRA_REPARACION,
        'total_mano_obra_reparacion': total_mano_obra_reparacion,
        'desglose_materiales': sorted(desglose_materiales, key=lambda x: x['material']),
        'total_materiales': total_materiales,
        'total_general': total_general,
    }

def _obtener_presupuesto_real(pedido):
    """
    Calcula el presupuesto REAL después de finalizar las tareas con precios de la fecha_finalizacion.
    - Mano de obra por revisión (PRECIO_REVISION_BASE * num_tareas)
    - Mano de obra por reparación (MANO_OBRA_REPARACION * num_tareas_reparacion_aprobadas)
      Solo se cobra si la tarea tiene materiales (no fue cancelada)
    - Suma de (precio_en_fecha_finalizacion * stockusado) de cada MaterialTarea
    """
    tareas = pedido.tarea_set.all()
    num_tareas = tareas.count()
    

    precio_revision_total = num_tareas * PRECIO_REVISION_BASE
    

    fecha_referencia = getattr(pedido, 'fecha_presupuesto', None) or getattr(pedido, 'fecha_finalizacion', None)
    

    materiales_agrupados = {}
    num_tareas_reparacion = 0
    
    for tarea in tareas:
        if tarea.tipoTarea == 'reparacion':
        
            tiene_materiales = False
            
    
            for mat_tarea in tarea.materialtarea_set.all():
                if mat_tarea.stockusado:
                    tiene_materiales = True
                    material = mat_tarea.material
              
                    precio_en_fecha = _obtener_precio_en_fecha(material, fecha_referencia)
                    material_id = material.id
                    if material_id not in materiales_agrupados:
                        materiales_agrupados[material_id] = {
                            'nombre': material.tipo,
                            'precio_unitario': precio_en_fecha,
                            'cantidad_total': Decimal('0'),
                        }
                    materiales_agrupados[material_id]['cantidad_total'] += mat_tarea.stockusado
            
            # Solo contar para mano de obra si tiene materiales (no fue cancelada)
            if tiene_materiales:
                num_tareas_reparacion += 1
    

    total_mano_obra_reparacion = num_tareas_reparacion * MANO_OBRA_REPARACION

    desglose_materiales = []
    total_materiales_real = Decimal('0.00')
    for mat_data in materiales_agrupados.values():
        subtotal = mat_data['cantidad_total'] * mat_data['precio_unitario']
        total_materiales_real += subtotal
        desglose_materiales.append({
            'material': mat_data['nombre'],
            'cantidad': mat_data['cantidad_total'],
            'precio_unitario': mat_data['precio_unitario'],
            'subtotal': subtotal,
        })
    
  
    total_general = precio_revision_total + total_mano_obra_reparacion + total_materiales_real
    
    return {
        'num_tareas': num_tareas,
        'precio_revision_unitario': PRECIO_REVISION_BASE,
        'precio_revision_total': precio_revision_total,
        'num_tareas_reparacion': num_tareas_reparacion,
        'precio_mano_obra_unitario': MANO_OBRA_REPARACION,
        'total_mano_obra_reparacion': total_mano_obra_reparacion,
        'desglose_materiales': sorted(desglose_materiales, key=lambda x: x['material']),
        'total_materiales_real': total_materiales_real,
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
    total_estimado = 0
    materiales_sugeribles = []
    for item in materiales_ficha:
        cantidad_sugerida = materiales_tarea.get(item.material_id, 0)
        subtotal = (item.material.precio_venta or 0) * cantidad_sugerida
        total_estimado += subtotal
        materiales_sugeribles.append(
            {
                'material_id': item.material_id,
                'material_tipo': item.material.tipo,
                'cantidad_maxima': item.cantidadrecomendada,
                'cantidad_sugerida': cantidad_sugerida,
                'costo_unitario': item.material.costo_unidad,
                'precio_venta': item.material.precio_venta,
                'subtotal': subtotal,
            }
        )

    return materiales_sugeribles, total_estimado


def _observacion_para_tarea(tarea, tipoobservacion):
    return Observacion.objects.filter(tarea=tarea, tipoobservacion=tipoobservacion).first()


def _actualizar_estado_pedido_si_corresponde(pedido):
    tareas_pedido = Tarea.objects.filter(pedido=pedido)
    if tareas_pedido.exists() and tareas_pedido.exclude(estado='terminada').count() == 0:
        if pedido.estado != 'terminado':
            pedido.estado = 'terminado'
            pedido.fecha_ultimo_cambio = timezone.now()
            pedido.save(update_fields=['estado', 'fecha_ultimo_cambio'])
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
        f"Teléfono: {pedido.cliente.telefono}",
        f"Correo: {pedido.cliente.correo}",
        f"Presupuesto estimado: ${_obtener_presupuesto_estimado(pedido)}",
        
    ]
    

    if pedido.estado in ('terminado', 'retirado', 'notificado'):
        presupuesto_real = _obtener_presupuesto_real(pedido)
        lineas.extend([
            "",
            "==== PRESUPUESTO REAL ====",
            f"Revisión de tareas ({presupuesto_real['num_tareas']}): ${presupuesto_real['precio_revision_total']}",
        ])
        
        if presupuesto_real['num_tareas_reparacion'] > 0:
            lineas.append(
                f"Mano de obra reparación ({presupuesto_real['num_tareas_reparacion']}): ${presupuesto_real['total_mano_obra_reparacion']}"
            )
        
        if presupuesto_real['desglose_materiales']:
            lineas.append("Materiales utilizados:")
            for mat in presupuesto_real['desglose_materiales']:
                lineas.append(f"  - {mat['material']}: {mat['cantidad']} x ${mat['precio_unitario']} = ${mat['subtotal']}")
        
        lineas.append(f"TOTAL REAL: ${presupuesto_real['total_general']}")

    lineas.extend([
        "",
        "Tareas incluidas:",
    ])

    if tareas.exists():
        for tarea in tareas:
            lineas.append(
                f"- Tarea {tarea.id} | Serie: {tarea.amortiguador.nroSerieamortiguador} | Estado: {tarea.estado}"
            )
    else:
        lineas.append("- Sin tareas asociadas")


    if pedido.cancelado:
        lineas.append("")
        lineas.append("** Este pedido ha sido cancelado **")


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
    if not request.user.is_authenticated:
        return redirect('login')

    operario = getattr(request.user, 'operario', None)
    rol = operario.role if operario else 'encargado'

 
    if operario and operario.role == 'operario':
        # 1. Últimas 5 tareas modificadas asignadas a este operario
        ultimas_tareas = Tarea.objects.filter(operario=operario).select_related('amortiguador', 'pedido').order_by('-id')[:5]

        # 2. Total de tareas de reparación terminadas por este operario
        reparaciones_terminadas = Tarea.objects.filter(
            operario=operario, 
            tipoTarea='reparacion', # <-- CORREGIDO: antes decía tipo='reparacion'
            estado='terminada'
        ).count()

        # 3. Métricas rápidas (KPIs)
        tareas_pendientes_op = Tarea.objects.filter(operario=operario, estado='pendiente').count()
        tareas_por_reparar_op = Tarea.objects.filter(operario=operario, estado='por reparar').count()
        tareas_en_reparacion_op = Tarea.objects.filter(operario=operario, estado='en reparacion').count()

        # 4. Gráfico del Operario: Distribución de Tareas por Tipo (Control vs Reparación)
        total_control = Tarea.objects.filter(operario=operario, tipoTarea='control').count() # <-- CORREGIDO
        total_reparacion = Tarea.objects.filter(operario=operario, tipoTarea='reparacion').count() # <-- CORREGIDO

        labels_operario = ['Control', 'Reparación']
        data_operario = [total_control, total_reparacion]

        context_operario = {
            'ultimas_tareas': ultimas_tareas,
            'reparaciones_terminadas': reparaciones_terminadas,
            'tareas_pendientes_op': tareas_pendientes_op,
            'tareas_por_reparar_op': tareas_por_reparar_op,
            'tareas_en_reparacion_op': tareas_en_reparacion_op,
            'labels_operario': labels_operario,
            'data_operario': data_operario,
            'role': 'operario',
        }
        return render(request, 'home_operario.html', context_operario)

    # =========================================================================
    # B. DASHBOARD PARA EL ENCARGADO DE MATERIALES
    # =========================================================================
    elif operario and operario.role == 'encargado_materiales':
        # 1. Materiales más sugeridos en tareas (Top 5)
        # ACÁ USAMOS materialtarea__stockrecomendado
        materiales_mas_sugeridos = Material.objects.annotate(
            total_sugerido=Coalesce(Sum('materialtarea__stockrecomendado'), 0)
        ).order_by('-total_sugerido')[:5]

        # 2. Materiales requeridos para tareas 'por reparar' que están sin stock / stock bajo
        # ACÁ USAMOS materialtarea__tarea__estado
        materiales_faltantes_tareas = Material.objects.filter(
            materialtarea__tarea__estado='por reparar',
            stockActual__lt=F('stockMinimo')
        ).distinct()

        # 3. KPIs de Inventario
        alertas_stock = Material.objects.filter(stockActual__lte=F('stockMinimo')).count()
        materiales_sin_stock = Material.objects.filter(stockActual=0).count()
        total_materiales = Material.objects.count()

        # 4. Gráfico Encargado de Materiales: Top 5 Insumos más sugeridos
        labels_materiales = [m.nombre for m in materiales_mas_sugeridos]
        data_materiales = [float(m.total_sugerido) for m in materiales_mas_sugeridos]

        context_materiales = {
            'materiales_mas_sugeridos': materiales_mas_sugeridos,
            'materiales_faltantes_tareas': materiales_faltantes_tareas,
            'alertas_stock': alertas_stock,
            'materiales_sin_stock': materiales_sin_stock,
            'total_materiales': total_materiales,
            'labels_materiales': labels_materiales,
            'data_materiales': data_materiales,
            'role': 'encargado_materiales',
        }
        return render(request, 'home_encargado_materiales.html', context_materiales)

    # =========================================================================
    # C. DASHBOARD PARA EL ENCARGADO GENERAL / ADMINISTRADOR
    # =========================================================================
    hoy = timezone.now()
    hace_30_dias = hoy - timedelta(days=30)
    seis_meses_atras = hoy - timedelta(days=180)

    # 1. KPIs
    pedidos_activos = Pedido.objects.filter(cancelado=False).exclude(
        estado__in=['terminado', 'retirado', 'notificado']
    )
    total_activos = pedidos_activos.count()
    
    pedidos_atrasados_30d = pedidos_activos.filter(
        fechaSalidaEstimada__lt=hoy,
        fechaSalidaEstimada__gte=hace_30_dias
    ).count()

    tareas_pendientes = Tarea.objects.filter(estado='pendiente').count()
    alertas_stock = Material.objects.filter(stockActual__lt=F('stockMinimo')).count()
    materiales_stock_bajo = Material.objects.filter(stockActual__lt=F('stockMinimo')).order_by('tipo')

    # 2. Gráfico 1: Ganancias
    pedidos_retirados = Pedido.objects.filter(
        estado='retirado', 
        cancelado=False, 
        fechaSalidaReal__gte=seis_meses_atras
    )
    
    ventas_por_mes = {}
    for p in pedidos_retirados:
        if p.fechaSalidaReal:
            mes_key = p.fechaSalidaReal.strftime('%Y-%m')
            ventas_por_mes[mes_key] = ventas_por_mes.get(mes_key, Decimal('0.00')) + (p.total_estimado or Decimal('0.00'))

    meses_es = {'01':'Ene', '02':'Feb', '03':'Mar', '04':'Abr', '05':'May', '06':'Jun', '07':'Jul', '08':'Ago', '09':'Sep', '10':'Oct', '11':'Nov', '12':'Dic'}
    meses_ordenados = sorted(ventas_por_mes.keys())
    
    labels_ganancias = [f"{meses_es[m.split('-')[1]]} {m.split('-')[0]}" for m in meses_ordenados]
    data_ganancias = [float(ventas_por_mes[m]) for m in meses_ordenados]

    # 3. Gráfico 2: Cancelados vs Retirados
    total_cancelados = Pedido.objects.filter(cancelado=True).count()
    total_retirados = Pedido.objects.filter(estado='retirado', cancelado=False).count()
    
    labels_comparativa = ['Retirados (Éxito)', 'Cancelados']
    data_comparativa = [total_retirados, total_cancelados]

    # 4. Listado de Operarios
    operarios_activos = Operario.objects.filter(role='operario').annotate(
        total_pendientes=Count('tarea', filter=Q(tarea__estado__in=['pendiente', 'por reparar', 'en reparacion'])),
        solo_pendientes=Count('tarea', filter=Q(tarea__estado='pendiente')),
        por_reparar=Count('tarea', filter=Q(tarea__estado='por reparar')),
        en_reparacion=Count('tarea', filter=Q(tarea__estado='en reparacion'))
    ).filter(total_pendientes__gt=0).order_by('-total_pendientes')

    context = {
        'total_activos': total_activos,
        'pedidos_atrasados_30d': pedidos_atrasados_30d,
        'tareas_pendientes': tareas_pendientes,
        'alertas_stock': alertas_stock,
        'materiales_stock_bajo': materiales_stock_bajo,
        'labels_ganancias': labels_ganancias,
        'data_ganancias': data_ganancias,
        'labels_comparativa': labels_comparativa,
        'data_comparativa': data_comparativa,
        'operarios_activos': operarios_activos,
        'role': 'encargado',
    }

    if getattr(request.user, 'is_superuser', False) or not operario or operario.role == 'encargado':
        return render(request, 'home.html', context)

    return redirect('login')
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
            return render(request, 'registration/login.html', {
                'show_error': True
            })
    return render(request, 'registration/login.html', {})

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
                        cliente=cliente,
                        fechaingreso=timezone.now()
                    )

                    return redirect('detalle_pedido', pedido_id=pedido.id)
                except Cliente.DoesNotExist:
                    context['error'] = "No se puede crear el pedido. Cliente no encontrado."

        return render(request, 'createpedido.html', context)
    
@role_required(['encargado'])
def detalle_pedido(request, pedido_id):
    pedido = get_object_or_404(Pedido, id=pedido_id)
    tareas = Tarea.objects.select_related('amortiguador', 'operario', 'pedido', 'pedido__cliente').filter(pedido=pedido).order_by('id')
    editar_plan = request.GET.get('editar_plan') == '1'
    operarios_disponibles = Operario.objects.filter(role='operario').order_by('nombre')
    mensaje_exito = None
    sincronizar_estado_pedido(pedido)

    tareas_reparacion_editables = tareas.filter(tipoTarea='reparacion', estado='por reparar')
    control= not(tareas.filter(tipoTarea='reparacion').exists())
    todastareasrevisadas = not tareas.exclude(estado__in=['terminada', 'por reparar']).exists() if tareas.exists() else False
  
    if tareas.exists() and tareas.exclude(estado='terminada').count() == 0:
        if pedido.estado not in ('terminado', 'retirado', 'notificado'):
            pedido.estado = 'terminado'
            pedido.fecha_ultimo_cambio = timezone
            if not pedido.fecha_finalizacion:
                pedido.fecha_finalizacion = timezone.now()
            pedido.save(update_fields=['estado', 'fecha_finalizacion', 'fecha_ultimo_cambio'])
    
    presupuesto_estimado = 0
    desglose_presupuesto = None
    presupuesto_real = None
    
    if pedido.estado in ('revisado', 'presupuestado', 'aprobado'):
        presupuesto_estimado = _obtener_presupuesto_estimado(pedido)
        desglose_presupuesto = _obtener_desglose_presupuesto(pedido)
    elif pedido.estado in ('terminado', 'retirado', 'notificado'):
  
        presupuesto_real = _obtener_presupuesto_real(pedido)
    


    if request.method == 'POST':
        accion = request.POST.get('accion')
        if accion == 'eliminar_tarea':
            tarea_id = request.POST.get('tarea_id')
            try:
                tarea = Tarea.objects.get(id=tarea_id, pedido=pedido)
                if tarea.estado != 'pendiente':
                    messages.error(request, 'Solo puedes eliminar tareas que estén pendientes.')
                    return redirect('detalle_pedido', pedido_id=pedido.id)
                
                # REGLA DE NEGOCIO: "Si hay alguna pendiente se pueden eliminar pero NO todas"
                if tareas.count() == 1:
                    messages.error(request, 'No puedes eliminar la única tarea del pedido. Si quieres cancelar el trabajo, elimina el pedido completo.')
                    return redirect('detalle_pedido', pedido_id=pedido.id)
                    
                tarea_serie = tarea.amortiguador.nroSerieamortiguador
                tarea.delete()
                
                # Si se borra una tarea, recalculamos el estado del pedido 
                # (Ej: si borrás la única pendiente y la otra ya estaba 'no revisada', el pedido podría cambiar)
                sincronizar_estado_pedido(pedido)
                
                messages.warning(request, f'Tarea del amortiguador {tarea_serie} eliminada correctamente.')
            except Tarea.DoesNotExist:
                messages.error(request, 'No se encontró la tarea a eliminar.')
            
            return redirect('detalle_pedido', pedido_id=pedido.id)
        elif accion == 'rechazar_sugerencia_rapida':
            tarea_id = request.POST.get('tarea_id')
            motivo = request.POST.get('motivo_devolucion', '').strip()
            
            try:
                tarea = Tarea.objects.get(id=tarea_id, pedido=pedido)
                if tarea.estado not in ('no revisada', 'por reparar'):
                    messages.error(request, 'Solo puedes devolver tareas que estén en revisión.')
                else:
                    observacion = Observacion.objects.filter(tarea=tarea).first()
                    
                    # Guardamos el motivo en el historial
                    if observacion:
                        fecha_str = timezone.now().strftime('%d/%m/%Y %H:%M')
                        nota_encargado = f"\n\n[DEVUELTO POR ENCARGADO - {fecha_str}]\nMotivo: {motivo}"
                        observacion.detalle_autogenerado += nota_encargado
                        observacion.save(update_fields=['detalle_autogenerado'])

                    # Reiniciamos la tarea a pendiente y le prendemos la alerta roja (devuelta=True)
                    tarea.estado = 'pendiente'
                    tarea.devuelta = True
                    tarea.fecha_ultimo_cambio = timezone.now()
                    tarea.save(update_fields=['estado', 'fecha_ultimo_cambio', 'devuelta'])

                    # Sincronizamos el pedido
                    sincronizar_estado_pedido(pedido)

                    messages.warning(request, f'La Tarea #{tarea.id} fue devuelta al operario con tus observaciones.')
            except Tarea.DoesNotExist:
                messages.error(request, 'No se encontró la tarea seleccionada.')
                
            return redirect('detalle_pedido', pedido_id=pedido.id)

 # Agregalo junto a tus otros "elif" en detalle_pedido
        elif accion == 'cambiar_tipo_comercial':
            tarea_id = request.POST.get('tarea_id')
            nuevo_tipo = request.POST.get('nuevo_tipo')
            
            try:
                tarea = Tarea.objects.get(id=tarea_id, pedido=pedido)
                if pedido.estado not in ['presupuestado', 'terminado']:
                    messages.error(request, 'Solo puedes modificar la decisión cuando el pedido está Presupuestado o Terminado.')
                else:
                    if nuevo_tipo in ['control', 'reparacion']:
                        tarea.tipoTarea = nuevo_tipo
                        # Si es control, se da por terminada. Si vuelve a reparación, se pone 'por reparar'
                        tarea.estado = 'terminada' if nuevo_tipo == 'control' else 'por reparar'
                        
                        # ¡NOTA! NO borramos los materiales acá. Así podés arrepentirte y volver a cambiarlos.
                        tarea.save(update_fields=['tipoTarea', 'estado'])
                        sincronizar_estado_pedido(pedido)
                        
                        messages.success(request, f'La Tarea #{tarea.id} se actualizó a {nuevo_tipo.upper()}. Presupuesto recalculado.')
            except Tarea.DoesNotExist:
                messages.error(request, 'No se encontró la tarea seleccionada.')
                
            return redirect('detalle_pedido', pedido_id=pedido.id)

        
        elif accion == 'editar_fecha_limite_pedido':
            nueva_fecha_raw = request.POST.get('nueva_fecha_limite')
            nueva_fecha, error = _validar_fecha_limite_pedido(nueva_fecha_raw, pedido)
            
            if error:
                messages.error(request, error)
            else:
                pedido.fechaSalidaEstimada = nueva_fecha
                pedido.fecha_ultimo_cambio = timezone.now()
                pedido.save(update_fields=['fechaSalidaEstimada', 'fecha_ultimo_cambio'])
                
                # Opcional: actualizamos también las tareas activas para que no queden desfasadas
                tareas.exclude(estado='terminada').update(fechaLimite=nueva_fecha)
                
                messages.success(request, 'Fecha límite del pedido actualizada correctamente.')
            return redirect('detalle_pedido', pedido_id=pedido.id)
        elif accion == 'terminar_revision_pedido':

            tareas_sin_tipo = tareas.filter(tipoTarea__isnull=True) | tareas.filter(tipoTarea='')
            if tareas_sin_tipo.exists():
                messages.error(request, 'No puedes terminar la revisión si hay tareas sin tipo definido.')
                return redirect('detalle_pedido', pedido_id=pedido.id)
            
         
            sincronizar_estado_pedido(pedido)
            
            if pedido.estado == 'revisado':
                messages.success(request, 'Revisión completada. Ya puedes solicitar la aprobación del presupuesto al cliente.')
            elif pedido.estado == 'presupuestado':
                messages.success(request, '¡Se generó el presupuesto! Ahora espera la aprobación del cliente.')
            else:
                messages.success(request, '¡El pedido ha sido finalizado como control (Sin repuestos)!')
            
            return redirect('detalle_pedido', pedido_id=pedido.id)
        elif accion == 'crear_tarea':
            return redirect('create_tarea', pedido_id=pedido.id)
        elif accion == 'editar_tarea_asignacion':
            tarea_id = request.POST.get('tarea_id')
            nuevo_operario_id = request.POST.get('operario')
            nueva_prioridad = request.POST.get('prioridad')
            
            try:
                tarea = Tarea.objects.get(id=tarea_id, pedido=pedido)
                if tarea.estado != 'pendiente':
                    messages.error(request, 'Solo puedes editar tareas que estén en estado pendiente.')
                else:
                    nuevo_operario = get_object_or_404(Operario, id=nuevo_operario_id)
                    tarea.operario = nuevo_operario
                    tarea.prioridad = nueva_prioridad
                    tarea.save(update_fields=['operario', 'prioridad'])
                    messages.success(request, f'Tarea #{tarea.id} actualizada correctamente.')
            except Tarea.DoesNotExist:
                messages.error(request, 'No se encontró la tarea a editar.')
                
            return redirect('detalle_pedido', pedido_id=pedido.id)

        elif accion == 'finalizar_creacion_pedido':

            pedido.estado = 'asignado'
            pedido.fecha_ultimo_cambio = timezone.now()
            pedido.save()
            messages.success(request, "Pedido confirmado y tareas asignadas a los operarios.")
            return redirect('detalle_pedido', pedido_id=pedido.id)

        elif accion == 'aprobar_sugerencia_rapida':
            tarea_id = request.POST.get('tarea_id')
            try:
                tarea = Tarea.objects.get(id=tarea_id, pedido=pedido)
                # Obtenemos la observación asociada
                observacion = Observacion.objects.filter(tarea=tarea).first()
                
                if observacion:
                    sugerencia = (observacion.sugerencia_tecnica or '').strip().lower()
                    
                    if sugerencia == 'reparacion':
                        tarea.estado = 'por reparar'
                    elif sugerencia == 'control':
                        tarea.estado = 'terminada' 
                        tarea.materialtarea_set.all().delete() 
                    
                    tarea.tipoTarea = sugerencia
                    tarea.devuelta = False
                    tarea.fecha_ultimo_cambio = timezone.now()
                    tarea.save(update_fields=['estado', 'tipoTarea', 'fecha_ultimo_cambio', 'devuelta'])
                    sincronizar_estado_pedido(pedido)
                    
                    messages.success(request, f'Sugerencia técnica aprobada para el amortiguador {tarea.amortiguador.nroSerieamortiguador}.')
                else:
                    messages.error(request, 'No se puede aprobar porque el operario aún no generó el diagnóstico.')
            except Tarea.DoesNotExist:
                messages.error(request, 'No se encontró la tarea seleccionada.')
                
            return redirect('detalle_pedido', pedido_id=pedido.id)

        elif accion == 'borrar_pedido':
            # REGLA DE NEGOCIO: Permitir borrar si está retirado o recién "asignado"
            if pedido.estado not in ('retirado', 'asignado'):
                messages.error(request, 'Solo puedes eliminar un pedido cuando está retirado o recién asignado (sin iniciar).')
                return redirect('detalle_pedido', pedido_id=pedido.id)

            pedido.delete()
            messages.warning(request, "Se eliminó el pedido y sus tareas asociadas.")
            return redirect('home')    
        elif accion == 'aprobar_presupuesto':
            if pedido.estado in ('revisado', 'presupuestado'):
   
                total = _obtener_presupuesto_estimado(pedido)
                pedido.total_estimado = total
                
                if tareas.filter(tipoTarea='reparacion').exists():
                    pedido.estado = 'aprobado'

                    pedido.fecha_ultimo_cambio = timezone.now()
                    pedido.fechaSalidaEstimada = timezone.now() + datetime.timedelta(days=7) 
                    messages.success(request, f'Presupuesto de ${total} aprobado. Las tareas están habilitadas para que los operarios reserven el stock y comiencen.')
                else:
                    pedido.estado = 'terminado'
                    messages.success(request, '¡El pedido ha sido finalizado como control, avisale al cliente!')

                pedido.save()

            else:
                messages.error(request, 'Solo se puede aprobar si el pedido está revisado o presupuestado.')
            return redirect('detalle_pedido', pedido_id=pedido.id)
        elif accion == 'cancelar_presupuesto':
            if pedido.estado == 'presupuestado':
                # 1. Borrar todos los MaterialTarea asociados a las tareas del pedido
                for tarea in tareas:
                    MaterialTarea.objects.filter(tarea=tarea).delete()
                    
 
                    observacion, created = Observacion.objects.get_or_create(
                        tarea=tarea,
                        defaults={'amortiguador': tarea.amortiguador}
                    )
                    observacion.comentariofinal = 'Pedido cancelado'
                    observacion.save(update_fields=['comentariofinal'])
                
             
                tareas.update(estado='terminada')
                
           
                pedido.estado = 'terminado'
                pedido.fecha_ultimo_cambio = timezone.now()
                pedido.cancelado = True
                pedido.save()
                
                messages.warning(request, 'Presupuesto cancelado. Se borraron los materiales sugeridos y el pedido se marcó como terminado.')
            else:
                messages.error(request, 'Solo se puede cancelar el presupuesto cuando el pedido está en estado presupuestado.')
            return redirect('detalle_pedido', pedido_id=pedido.id)
        elif accion == 'finalizar_pedido':
            fecha_limite_raw = request.POST.get('fecha_limite')
            fecha_limite, error = _validar_fecha_limite_pedido(fecha_limite_raw, pedido)
            if error:
                messages.error(request, error)
                return redirect('detalle_pedido', pedido_id=pedido.id)

            tareas.exclude(estado='terminada').update(fechaLimite=fecha_limite)
            pedido.fechaSalidaEstimada = fecha_limite
            pedido.fecha_ultimo_cambio = timezone.now()
            pedido.save(update_fields=['fechaSalidaEstimada', 'fecha_ultimo_cambio'])
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
            pedido.fecha_ultimo_cambio = timezone.now()
            pedido.save(update_fields=['fechaSalidaEstimada', 'fecha_ultimo_cambio'])
            messages.success(request, 'Plan actualizado. Puedes editar materiales desde cada tarea de reparacion.')
            return redirect('detalle_pedido', pedido_id=pedido.id)
        elif accion == 'emitir_comprobante':
            if pedido.estado not in ('terminado', 'notificado', 'retirado', 'revisado'):
                messages.error(request, 'El comprobante solo se puede emitir para pedidos terminados.')
                return redirect('detalle_pedido', pedido_id=pedido.id)

         
            pdf_bytes = _generar_comprobante_pdf(pedido, tareas)
            
         
            comprobante, created = Comprobante.objects.get_or_create(pedido=pedido)
            comprobante.contenido = pdf_bytes.decode('latin-1', errors='replace')
            comprobante.save()
            

            if created:
                _guardar_historico_precios_pedido(pedido, concepto='comprobante_emitido')
            
            response = HttpResponse(pdf_bytes, content_type='application/pdf')
            response['Content-Disposition'] = f'attachment; filename="comprobante_pedido_{pedido.id}.pdf"'
            return response
        elif accion == 'enviar_comprobante':
            if pedido.estado not in ('terminado', 'notificado', 'retirado', 'revisado'):
                messages.error(request, 'El comprobante solo se puede enviar para pedidos terminados.')
                return redirect('detalle_pedido', pedido_id=pedido.id)

            destino = (pedido.cliente.correo or '').strip()
            if not destino:
                messages.error(request, 'El cliente no tiene correo cargado.')
                return redirect('detalle_pedido', pedido_id=pedido.id)
            

            try:
                # 1. Obtener o generar el PDF
                try:
                    comprobante = Comprobante.objects.get(pedido=pedido)
                    pdf_bytes = comprobante.contenido.encode('latin-1', errors='replace')
                except Comprobante.DoesNotExist:
                    pdf_bytes = _generar_comprobante_pdf(pedido, tareas)
                    comprobante = Comprobante.objects.create(pedido=pedido)
                    comprobante.contenido = pdf_bytes.decode('latin-1', errors='replace')
                    comprobante.save()
                    
                # 2. Preparar el correo
                mail = EmailMessage(
                    subject=f'Comprobante pedido #{pedido.id}',
                    body=(
                        f'Hola {pedido.cliente.nombre},\n\n'
                        f'Tu pedido #{pedido.id} se encuentra {pedido.estado}.\n' # Ojo: acá dirá 'terminado' si no lo cambiaste antes
                        'Adjuntamos el comprobante en PDF.\n\n'
                        'Saludos.'
                    ),
                    to=[destino],
                )
                mail.attach(f'comprobante_pedido_{pedido.id}.pdf', pdf_bytes, 'application/pdf')
                
                # 3. Enviar el correo
                mail.send(fail_silently=False)
                if pedido.estado == 'retirado':
                    messages.warning(request, f'Comprobante enviado a {destino}, pero el pedido ya fue retirado.')
                else:
                # 4. SOLO SI EL ENVÍO FUE EXITOSO, actualizamos el estado
                    pedido.estado = 'notificado'
                    pedido.fecha_ultimo_cambio = timezone.now()
                    # REGLA: Eliminar materiales de tareas que quedaron definitivamente en 'control'
                    for t in tareas.filter(tipoTarea='control'):
                        t.materialtarea_set.all().delete()
                    # Actualizamos ambos campos a la vez
                    pedido.save(update_fields=['estado', 'fecha_ultimo_cambio']) 

                if settings.EMAIL_BACKEND == 'django.core.mail.backends.console.EmailBackend':
                    messages.warning(
                        request,
                        f'Comprobante generado para {destino}, pero el proyecto está en modo consola (no se envió un mail real).'
                    )
                else:
                    messages.success(request, f'Comprobante enviado a {destino}.')
                    
            except Exception as exc:
                messages.error(request, f'No se pudo enviar el comprobante: {exc}')

            return redirect('detalle_pedido', pedido_id=pedido.id)
        elif accion == 'retirar_pedido':
            if pedido.estado != 'notificado':
                messages.error(request, 'Solo los pedidos notificados pueden ser retirados.')
                return redirect('detalle_pedido', pedido_id=pedido.id)

            pedido.estado = 'retirado'
            pedido.fechaSalidaReal = timezone.now()
            pedido.fecha_ultimo_cambio = timezone.now()
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
        'presupuesto_real': presupuesto_real,
        'control': control,
        'operarios_disponibles': operarios_disponibles,
        'todastareasrevisadas': todastareasrevisadas,
        'comprobante': pedido.comprobante if hasattr(pedido, 'comprobante') else None,
        'hoy': timezone.now().date(),
    }
    return render(request, 'detalle_pedido.html', context)


def create_tarea(request, pedido_id):
    operarios = Operario.objects.filter(role='operario').annotate(
        tareas_pendientes=Count(
            'tarea',
            filter=Q(tarea__estado__in=['por reparar', 'pendiente', 'en reparacion'])
        )
    ).order_by('tareas_pendientes')
    
    fichas = Fichaamortiguador.objects.all()
    pedido = get_object_or_404(Pedido, id=pedido_id)
    
    # 1. Obtenemos las series cargadas
    series_cargadas = list(Tarea.objects.filter(pedido=pedido).values_list('amortiguador__nroSerieamortiguador', flat=True))
    
    # ACÁ ESTÁ EL SECRETO: convertimos a string (str) antes de hacer upper() para evitar el error del 'int'
    series_cargadas_upper = [str(s).strip().upper() for s in series_cargadas]
    
    context = { 
        'operarios': operarios, 
        'fichas': fichas, 
        'pedido': pedido, 
        'series_en_pedido': series_cargadas 
    }
    
    if request.method == 'POST':
        accion = request.POST.get('accion')
        
        # ========================================================
        # VALIDACIÓN ESTRICTA DE BACKEND (CANDADO DE SEGURIDAD)
        # ========================================================
        if accion in ['buscar', 'crear_amortiguador_tarea']:
            # Aseguramos que lo que viene del form sea tratado como texto
            nro_serie_input = str(request.POST.get('nroSerieamortiguador', '')).strip().upper()
            if nro_serie_input in series_cargadas_upper:
                context['error_backend'] = f'El amortiguador serie {nro_serie_input} ya pertenece a una tarea de este pedido.'
                return render(request, 'create_tarea.html', context)
                
        elif accion == 'crear_tarea':
            id_amortiguador = request.POST.get('id_amortiguador')
            amort_obj = Amortiguador.objects.filter(id=id_amortiguador).first()
            # ¡LA SOLUCIÓN APLICADA AQUÍ CON str()!
            if amort_obj and str(amort_obj.nroSerieamortiguador).strip().upper() in series_cargadas_upper:
                context['error_backend'] = f'El amortiguador serie {amort_obj.nroSerieamortiguador} ya pertenece a una tarea de este pedido.'
                return render(request, 'create_tarea.html', context)
        # ========================================================
        
        # --- CASO 1: SOLO BUSCAR EL AMORTIGUADOR ---
        if accion == 'buscar':
            nro_serie_input = request.POST.get('nroSerieamortiguador')
            try:
                amortiguador = Amortiguador.objects.get(nroSerieamortiguador=nro_serie_input)
                context['amortiguador'] = amortiguador
            except Amortiguador.DoesNotExist:
                context['no_amortiguador'] = True
                context['nroSerieamortiguador'] = nro_serie_input
                
            return render(request, 'create_tarea.html', context)
            
        # --- CASO 2: CREAR EL AMORTIGUADOR (PORQUE NO EXISTÍA) Y LUEGO LA TAREA ---
        elif accion == 'crear_amortiguador_tarea':
            nro_serie_input = request.POST.get('nroSerieamortiguador')
            ficha_id = request.POST.get('ficha_amortiguador') 
            
            ficha_seleccionada = get_object_or_404(Fichaamortiguador, id=ficha_id)
            
            amortiguador = Amortiguador.objects.create(
                nroSerieamortiguador=nro_serie_input,
                fichaamortiguador=ficha_seleccionada,
                tipo=request.POST.get('tipo_amortiguador', '') 
            )
            
            operario = get_object_or_404(Operario, id=request.POST.get('operario'))
            
            tarea = Tarea.objects.create(
                prioridad=request.POST.get('prioridad'),
                amortiguador=amortiguador,
                operario=operario,
                pedido=pedido,
                estado='pendiente'
            ) 
            return redirect('detalle_pedido', pedido_id=pedido.id)
            
        # --- CASO 3: EL AMORTIGUADOR YA EXISTÍA Y CREAMOS SOLO LA TAREA ---
        elif accion == 'crear_tarea':
            operario = get_object_or_404(Operario, id=request.POST.get('operario'))
            amortiguador = get_object_or_404(Amortiguador, id=request.POST.get('id_amortiguador'))
            
            tarea = Tarea.objects.create(
                prioridad=request.POST.get('prioridad'),
                amortiguador=amortiguador,
                operario=operario,
                pedido=pedido,
                estado='pendiente'
            ) 
            return redirect('detalle_pedido', pedido_id=pedido.id)

    return render(request, 'create_tarea.html', context)

@login_required
@role_required(['operario'])

@role_required(['operario'])
def paneltareas(request):
    operario_actual = request.user.operario 
    estados_activos = ['pendiente', 'por reparar', 'en reparacion']
    
    # REGLA DE NEGOCIO: 
    # Traemos las tareas del operario pero EXCLUIMOS las que pertenecen 
    # a pedidos en estado 'pendiente' (que el encargado aún no confirmó).
    tareas = Tarea.objects.select_related('pedido', 'amortiguador', 'operario').filter(
        operario=operario_actual
    ).exclude(
        Q(pedido__estado='pendiente') | Q(pedido__estado='presupuestado')
    ).order_by('-id')

    # Filtro por búsqueda de texto
    query = request.GET.get('q', '').strip()
    if query:
        tareas = tareas.filter(
            Q(id__icontains=query) | 
            Q(amortiguador__nroSerieamortiguador__icontains=query)
        )

    # Filtro por estado
    estado_filtro = request.GET.get('estado')
    if estado_filtro:
        tareas = tareas.filter(estado=estado_filtro)
    else:
        # Si no hay filtro, mostramos los estados activos de la bandeja
        tareas = tareas.filter(estado__in=estados_activos)

    context = {
        'tareas': tareas,
        'estados_disponibles': estados_activos, 
        'query': query,
        'estado_seleccionado': estado_filtro
    }
    return render(request, 'paneltareas.html', context)



@role_required(['operario', 'encargado'])
def detalle_tarea(request, tarea_id):
    tarea = get_object_or_404(Tarea, id=tarea_id)
    if not _can_access_tarea(request, tarea):
        return HttpResponseForbidden('No tienes permisos para ver esta tarea.')

    user_role = _get_request_role(request)
    accion = request.POST.get('accion') if request.method == 'POST' else None

    if request.method == 'POST' and user_role == 'encargado' and accion != 'eliminar_tarea':
        messages.info(request, 'La vista del encargado es solo de consulta.')
        return redirect('detalle_pedido', pedido_id=tarea.pedido.id)

    context = {'tarea': tarea, 'user_role': user_role}
    

    observacion = Observacion.objects.filter(tarea=tarea).first()
    context['observacion'] = observacion
    
    materialxamortiguador = MaterialFichaAmortiguador.objects.select_related('material').filter(fichaamortiguador=tarea.amortiguador.fichaamortiguador)
    materialxtarea = MaterialTarea.objects.select_related('material').filter(tarea=tarea)
    
    context['materialxtarea'] = materialxtarea
    context['materialxamortiguador'] = materialxamortiguador
    context['materiales_sugeribles'] = _materiales_para_sugerencia_tarea(tarea)
    materiales_sugeribles, total_estimado_materiales = _materiales_para_sugerencia_tarea(tarea)
    context['materiales_sugeribles'] = materiales_sugeribles
    context['total_estimado_materiales'] = total_estimado_materiales
    materiales_sugeribles_visibles = [item for item in materiales_sugeribles if item['cantidad_sugerida'] > 0]
    context['materiales_sugeribles_visibles'] = materiales_sugeribles_visibles
    context['mostrar_materiales_sugeridos'] = bool(
        observacion and observacion.sugerencia_tecnica == 'reparacion' and materiales_sugeribles_visibles
    )
 
    tipo_sugerido = observacion.sugerencia_tecnica if observacion else None
    context['tipo_sugerido'] = tipo_sugerido
    
    
    materiales_faltantes = []
    if tarea.estado == 'por reparar' and materialxtarea.exists():
        for mt in materialxtarea:
            mat = Material.objects.get(id=mt.material_id)
            reservado = int(mat.stockreservado or 0)
            actual = int(mat.stockActual or 0)
            requerido = int(mt.stockrecomendado or 0)
            disponible = actual - reservado
            
            if requerido > disponible:
                materiales_faltantes.append({
                    'material': mat.tipo,
                    'requerido': requerido,
                    'disponible': max(disponible, 0),
                    'falta': requerido - max(disponible, 0)
                })
    
    context['materiales_faltantes'] = materiales_faltantes
    context['puede_reservar'] = len(materiales_faltantes) == 0

    if request.method == 'POST':
        if not _can_perform_tarea_action(request, tarea, accion):
            return HttpResponseForbidden('No tienes permisos para realizar esta acción.')

        if accion == 'eliminar_tarea':
            if tarea.estado != 'pendiente':
                messages.error(request, 'Solo puedes eliminar tareas en estado pendiente.')
                return redirect('detalle_pedido', pedido_id=tarea.pedido.id)

            pedido_id = tarea.pedido_id
            tarea_serie = tarea.amortiguador.nroSerieamortiguador
            tarea.delete()
            messages.warning(request, f'Tarea del amortiguador {tarea_serie} eliminada correctamente.')
            return redirect('detalle_pedido', pedido_id=pedido_id)


        if accion == 'terminarobservacioncontrol':
            if tarea.estado != 'pendiente':
                messages.error(request, 'Solo puedes cerrar observaciones cuando la tarea esta pendiente.')
                return redirect('detalle_tarea', tarea_id=tarea.id)

            if not observacion:
                messages.error(request, 'Debes cargar el diagnóstico antes de cerrar la revision.')
                return redirect('detalle_tarea', tarea_id=tarea.id)

            tarea.estado = 'no revisada'
            tarea.pedido.fecha_ultimo_cambio = timezone.now()
            tarea.fecha_ultimo_cambio = timezone.now()
            tarea.save(update_fields=['estado'])
            
            # MAGIA: Sincronizamos el pedido
            cambio_pedido = sincronizar_estado_pedido(tarea.pedido)
            
            context['class'] = 'alert alert-success'
            context['message'] = 'Has finalizado las observaciones de control de calidad.'
            
            if cambio_pedido and tarea.pedido.estado == 'revisado':
                messages.info(request, 'Todas las tareas fueron diagnosticadas. El pedido pasó a revisión del encargado.')
                
            return redirect('home')
       
            

        elif accion == 'guardar_tipo_materiales':
            if tarea.estado not in ('no revisada', 'terminada', 'por reparar'):
                messages.error(request, 'Solo puedes guardar tipo y materiales cuando la tarea esta en revision o por reparar.')
                return redirect('detalle_tarea', tarea_id=tarea.id)

            nuevo_tipo = (request.POST.get('tipoTarea') or '').strip()
            if nuevo_tipo not in ('control', 'reparacion'):
                messages.error(request, 'Tipo invalido.')
                return redirect('detalle_tarea', tarea_id=tarea.id)

            tipo_actual = (tarea.tipoTarea or '').strip()
            cambio_de_tipo = tipo_actual != nuevo_tipo

            with transaction.atomic():
                tarea.tipoTarea = nuevo_tipo
          
                tarea.estado = 'por reparar' if nuevo_tipo == 'reparacion' else 'terminada'
                tarea.fecha_ultimo_cambio = timezone.now()
                tarea.pedido.fecha_ultimo_cambio = timezone.now()
                tarea.save(update_fields=['tipoTarea', 'estado'])


            sincronizar_estado_pedido(tarea.pedido)

            if cambio_de_tipo:
                messages.success(request, 'Tipo y materiales guardados correctamente.')
            else:
                messages.success(request, 'Materiales actualizados correctamente.')


            return redirect('detalle_pedido', pedido_id=tarea.pedido.id)
        

        elif accion == 'confirmarreparacion':
            # ... (Toda la validación inicial de confirmarreparacion queda igual) ...
            nuevo_tipo = request.POST.get('confirmarreparacion')
            tipo_actual = (tarea.tipoTarea or '').strip()
            cambio_de_tipo = tipo_actual != nuevo_tipo
            tarea.devuelta = False

            tarea.tipoTarea = nuevo_tipo
            tarea.estado = 'terminada' if nuevo_tipo == 'control' else 'por reparar'
            tarea.fecha_ultimo_cambio = timezone.now()
            tarea.pedido.fecha_ultimo_cambio = timezone.now()
            tarea.save(update_fields=['tipoTarea', 'estado', 'devuelta', 'fecha_ultimo_cambio', 'pedido__fecha_ultimo_cambio'])
            
            
            sincronizar_estado_pedido(tarea.pedido)
            
            messages.success(request, f'La tarea quedó confirmada como {nuevo_tipo}.')
            return redirect('detalle_pedido', pedido_id=tarea.pedido.id)


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
                     
                        existente.materiales = json.dumps(faltantes_detalle, ensure_ascii=True)
                        existente.save(update_fields=['materiales'])
                    else:
                        Notificacion.objects.create(
                            tarea=tarea,
                            materiales=json.dumps(faltantes_detalle, ensure_ascii=True),
                        )

                    messages.error(request, f'Stock insuficiente: {len(faltantes)} material(es) no disponible(s). Revisa las cantidades faltantes arriba.')
                    return redirect('detalle_tarea', tarea_id=tarea.id)

                for mt in materiales_tarea:
                    mat = Material.objects.select_for_update().get(id=mt.material_id)
                    incremento = int(mt.stockrecomendado or 0)
                    mat.stockreservado = int(mat.stockreservado or 0) + incremento
                    mat.save(update_fields=['stockreservado'])

           
                Notificacion.objects.filter(tarea=tarea, resolved=False).update(resolved=True)

                tarea.estado = 'en reparacion'
                tarea.fecha_ultimo_cambio = timezone.now()
                tarea.fecha_inicio_reparacion = timezone.now()
                tarea.save(update_fields=['estado','fecha_ultimo_cambio','fecha_inicio_reparacion'])
                
      
            sincronizar_estado_pedido(tarea.pedido)

            messages.success(request, 'Materiales reservados correctamente.')
            return redirect('detalle_tarea', tarea_id=tarea.id)


        elif accion == 'finalizartarea':
            if tarea.estado != 'en reparacion':
                messages.error(request, 'Solo se puede finalizar una tarea en reparacion.')
                return redirect('detalle_tarea', tarea_id=tarea.id)

            # Capturamos el nuevo valor del diagrama final
            valor_diag_final = request.POST.get('valor_diagrama_final')
            if not valor_diag_final:
                messages.error(request, 'Debes ingresar el valor final del diagrama de fuerza.')
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
                        errores.append(f"Stock insuficiente en {mat.tipo}: falta {extra - max(libre, 0)} adicional(es).")
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
                tarea.fecha_finalizacion = timezone.now()
                tarea.fecha_ultimo_cambio = timezone.now()
                tarea.save(update_fields=['estado', 'fecha_finalizacion', 'fecha_ultimo_cambio'])
                Notificacion.objects.filter(tarea=tarea, resolved=False).update(resolved=True)

                try:
                    observacion = Observacion.objects.get(tarea=tarea)
                    
                    # Guardamos el valor final del diagrama de fuerza
                    try:
                        observacion.valor_diagrama_final = Decimal(valor_diag_final.replace(',', '.'))
                    except (ValueError, TypeError):
                        pass

                    if tarea.tipoTarea == 'control':
                        observacion.comentariofinal = 'Tipo tarea: control'
                    elif tarea.tipoTarea == 'reparacion':
                        lineas_materiales = []
                        for mt in MaterialTarea.objects.select_related('material').filter(tarea=tarea):
                            if mt.stockusado:
                                lineas_materiales.append(f"- {mt.material.nombre}: {mt.stockusado} {mt.material.unidad}")
                        if lineas_materiales:
                            observacion.comentariofinal = "Materiales utilizados:\n" + "\n".join(lineas_materiales)

                    observacion.save(update_fields=['comentariofinal', 'valor_diagrama_final'])
                except Observacion.DoesNotExist:
                    pass

                sincronizar_estado_pedido(tarea.pedido)

            messages.success(request, 'Tarea finalizada y stock actualizado.')

            if tarea.pedido.estado == 'terminado':
                messages.success(request, 'Todas las tareas finalizaron. El pedido pasó a terminado.')

            return redirect('detalle_tarea', tarea_id=tarea.id)

        elif accion == 'devolver_tarea':
            # Verificamos que sea el encargado
            if user_role != 'encargado':
                return HttpResponseForbidden('Solo el encargado puede devolver tareas.')
                
            if tarea.estado not in ('no revisada', 'por reparar'):
                messages.error(request, 'Solo puedes devolver tareas que estén en revisión.')
                return redirect('detalle_tarea', tarea_id=tarea.id)

            motivo = request.POST.get('motivo_devolucion', '').strip()
            
            # Anotamos el motivo directamente en el comentario autogenerado del sistema para mantener el historial
            if observacion:
                fecha_str = timezone.now().strftime('%d/%m/%Y %H:%M')
                nota_encargado = f"\n\n[DEVUELTO POR ENCARGADO - {fecha_str}]\nMotivo: {motivo}"
                observacion.detalle_autogenerado += nota_encargado
                observacion.save(update_fields=['detalle_autogenerado'])

            # Reiniciamos la tarea
            tarea.estado = 'pendiente'
            tarea.devuelta = True
            tarea.fecha_ultimo_cambio = timezone.now()
            tarea.save(update_fields=['estado', 'fecha_ultimo_cambio', 'devuelta'])

            # Sincronizamos el pedido (volverá a 'en curso')
            sincronizar_estado_pedido(tarea.pedido)

            messages.warning(request, 'La tarea fue devuelta al operario para su corrección.')
            return redirect('detalle_pedido', pedido_id=tarea.pedido.id)
        elif accion == 'agregarmaterialtarea':

            if tarea.estado not in ('terminada', 'por reparar') or tarea.pedido.estado not in ('revisado', 'por reparar'):

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
        
     
        texto_sistema = f"SUGERENCIA TÉCNICA: {sugerencia.upper()}\n"
        
       
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
    
        obs, _ = Observacion.objects.update_or_create(
            tarea=tarea,
            defaults={
                'amortiguador': tarea.amortiguador,
                'sugerencia_tecnica': sugerencia,
                'valor_diagrama': valor_diag,
                'detalle_operario': comentario_operario,     
                'detalle_autogenerado': texto_sistema       
            }
        )
        tarea.devuelta = False
        tarea.fecha_ultimo_cambio = timezone.now()
        tarea.pedido.fecha_ultimo_cambio = timezone.now()
        tarea.save(update_fields=['estado', 'fecha_ultimo_cambio', 'devuelta', 'fecha_inicio_reparacion', 'tipoTarea'])
        messages.success(request, 'Diagnóstico completo guardado.')
        return redirect('detalle_tarea', tarea_id=tarea.id)

    materiales_sugeribles, total_estimado_materiales = _materiales_para_sugerencia_tarea(tarea)
    context = {
        'tarea': tarea,
        'materiales_sugeribles': materiales_sugeribles,
        'total_estimado_materiales': total_estimado_materiales,
        'ficha': tarea.amortiguador.fichaamortiguador,
        'obs': getattr(tarea, 'observacion', None)
    }
    return render(request, 'form_observacion_unica.html', context)





@role_required(['encargado'])
def listapedidos(request):
   
    estados_validos = ['asignado', 'en curso', 'revisado', 'terminado', 'notificado', 'aprobado', 'retirado', 'presupuestado']
    
    pedidos = Pedido.objects.select_related('cliente').annotate(
        tareas_count=Count('tarea', distinct=True)
    ).order_by('-id')
    for pedido in pedidos:
        sincronizar_estado_pedido(pedido)


    if request.method == 'POST':
        accion = request.POST.get('accion')
        if accion == 'borrar_pedido':
            pedido_id = request.POST.get('pedido_id')
            pedido = get_object_or_404(Pedido, id=pedido_id)
            if pedido.estado != 'retirado':
                messages.error(request, 'Solo puedes eliminar un pedido cuando está retirado.')
                return redirect('listapedidos')

            pedido.delete()
            messages.warning(request, f'Pedido #{pedido_id} eliminado correctamente.')
            return redirect('listapedidos')

  
    query = request.GET.get('q', '').strip()
    if query:
   
        pedidos = pedidos.filter(
            Q(id__icontains=query) | Q(cliente__dni__icontains=query)
        )

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

    tarea = get_object_or_404(Tarea, id=tarea_id)
    amortiguador = tarea.amortiguador
    
 
    observaciones = Observacion.objects.filter(amortiguador=amortiguador).order_by('-fecha')
    

    context = {
        'amortiguador': amortiguador, 
        'observaciones': observaciones, 
        'id_pedido': tarea.pedido.id
    }
    return render(request, 'historial_amortiguador.html', context)


@role_required(['encargado'])
def descargar_comprobante(request, pedido_id):
    """Descargar el comprobante guardado de un pedido"""
    pedido = get_object_or_404(Pedido, id=pedido_id)
    
    try:
        comprobante = Comprobante.objects.get(pedido=pedido)
        pdf_bytes = comprobante.contenido.encode('latin-1', errors='replace')
        
        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="comprobante_pedido_{pedido.id}.pdf"'
        return response
    except Comprobante.DoesNotExist:
        messages.error(request, 'El comprobante no existe para este pedido.')
        return redirect('detalle_pedido', pedido_id=pedido.id)
    return render(request, 'historial_amortiguador.html', context)
"""
URL configuration for camav project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.views.generic.base import RedirectView
from amortiguador import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', views.home, name='home'),
    path('createpedido/', views.createpedido, name='createpedido'),
    path('detalle_pedido/<int:pedido_id>/', views.detalle_pedido, name='detalle_pedido'),
    path('create_tarea/<int:pedido_id>/', views.create_tarea, name='create_tarea'),
    path('paneltareas/', views.paneltareas, name='paneltareas'),
    path('detalle_tarea/<int:tarea_id>/', views.detalle_tarea, name='detalle_tarea'),
   

    path('tarea/<int:tarea_id>/observacion/', views.crear_o_editar_observacion, name='crear_o_editar_observacion'),
    path('inventario/', views.control_inventario, name='control_inventario'),
    path('inventario/material/<int:material_id>/', views.detalle_material, name='detalle_material'),
    path('inventario/buscar-proveedor/', views.buscar_proveedor_api, name='buscar_proveedor_api'),
    path('inventario/informe-stock/', views.informe_stock_minimo, name='informe_stock'),
    path('inventario/generar-pdf-stock/', views.generar_pdf_stock, name='generar_pdf_stock'),


    path('fichas/', views.lista_fichas, name='lista_fichas'),
    path('fichas/<int:ficha_id>/', views.detalle_ficha, name='detalle_ficha'),

    path('operarios/', views.lista_operarios, name='lista_operarios'),
    path('operarios/<int:operario_id>/', views.detalle_operario, name='detalle_operario'),
    path('operarios/<int:operario_id>/editar/', views.editar_operario, name='editar_operario'),
    path('operarios/crear/', views.crear_operario, name='crear_operario'),

    path('listapedidos/', views.listapedidos, name='listapedidos'),
    path('panel_notificaciones/', views.panel_notificaciones, name='panel_notificaciones'),
    path('historial_amortiguador/<int:tarea_id>/', views.historial_amortiguador, name='historial_amortiguador'),
    path('login/', RedirectView.as_view(url='/accounts/login/', permanent=False)),
    # auth
    path('accounts/', include('django.contrib.auth.urls')),

]


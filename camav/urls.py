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
from django.urls import path
from amortiguador import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', views.home, name='home'),
    path('createpedido/', views.createpedido, name='createpedido'),
    path('detalle_pedido/<int:pedido_id>/', views.detalle_pedido, name='detalle_pedido'),
    path('create_tarea/<int:pedido_id>/', views.create_tarea, name='create_tarea'),
    path('paneltareas/', views.paneltareas, name='paneltareas'),
    path('detalle_tarea/<int:tarea_id>/', views.detalle_tarea, name='detalle_tarea'),
    path('create_observacion/<int:tarea_id>/', views.create_observacion, name='create_observacion'),

]


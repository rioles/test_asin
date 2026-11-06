"""
URL configuration for test1 project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
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

from django.contrib import admin
from django.urls import path, include
from test1.views.inscription_view import (
    ConvocationView,
    InscriptionCreateView,
    InscritsCentreView,
    RechercheInscritsView,
)

api_concours_patterns = [
    path('inscriptions', InscriptionCreateView.as_view(), name='inscription-create'),
    path('inscriptions/<int:pk>/convocation', ConvocationView.as_view(), name='convocation'),
    path('centres/<str:code>/inscrits', InscritsCentreView.as_view(), name='centre-inscrits'),
    path('inscrits/recherche', RechercheInscritsView.as_view(), name='inscrits-recherche'),
]

api_v1_patterns = [
 
]

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/v1/', include(api_v1_patterns)),
    path('api/', include(api_concours_patterns)),
]
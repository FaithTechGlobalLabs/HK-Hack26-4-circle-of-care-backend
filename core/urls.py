from django.contrib import admin
from django.urls import include, path

admin.site.site_header = "Circle of Care admin"
admin.site.site_title = "Circle of Care"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("care.urls")),
]

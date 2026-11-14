from django.urls import path, re_path

from . import api, views

urlpatterns = [
    path("", views.home, name="home"),
    # Accept the webhook with or without the trailing slash; Django can't redirect a POST.
    re_path(r"^twilio/whatsapp/?$", views.twilio_webhook, name="twilio_webhook"),
    path("simulator/", views.simulator, name="simulator"),
    path("simulator/send/", views.simulator_send, name="simulator_send"),
    path("simulator/reset/", views.simulator_reset, name="simulator_reset"),
    path("board/", views.board, name="board"),
    path("board/offers/", views.offerings, name="offerings"),
    path("board/login/", views.board_login, name="board_login"),
    # JSON API for the Next.js board
    path("api/requests/", api.request_list, name="api_requests"),
    path("api/requests/<int:pk>/", api.request_detail, name="api_request"),
    path("api/requests/<int:pk>/offers/", api.create_offer, name="api_offers"),
    path("api/offerings/", api.offering_list, name="api_offerings"),
]

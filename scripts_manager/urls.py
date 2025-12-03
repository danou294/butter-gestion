from django.urls import path
from . import views
from . import restaurants_views
from . import photos_views
from . import users_views
from . import notifications_views
from . import auth_views

app_name = 'scripts_manager'

urlpatterns = [
    # Authentification
    path('login/', auth_views.login_view, name='login'),
    # path('register/', auth_views.register_view, name='register'),  # Inscription désactivée
    path('logout/', auth_views.logout_view, name='logout'),
    
    path('', views.index, name='index'),
    
    # Export
    path('export/', views.export_index, name='export_index'),
    path('export/run/', views.run_export, name='run_export'),
    
    # Upload service account désactivé - fichier fixe
    # path('upload-credentials/', views.upload_credentials, name='upload_credentials'),
    
    # Download exports
    path('download/<path:file_path>', views.download_file, name='download_file'),
    path('list-exports/', views.list_exports, name='list_exports'),
    
    # Task status
    path('task/<str:task_id>/', views.get_task_status, name='get_task_status'),
    
    # CRUD Restaurants
    path('restaurants/', restaurants_views.restaurants_list, name='restaurants_list'),
    path('restaurants/create/', restaurants_views.restaurant_create, name='restaurant_create'),
    path('restaurants/<str:restaurant_id>/', restaurants_views.restaurant_detail, name='restaurant_detail'),
    path('restaurants/<str:restaurant_id>/edit/', restaurants_views.restaurant_edit, name='restaurant_edit'),
    path('restaurants/<str:restaurant_id>/delete/', restaurants_views.restaurant_delete, name='restaurant_delete'),
    path('restaurants/<str:restaurant_id>/json/', restaurants_views.restaurant_get_json, name='restaurant_get_json'),
    
    # Import Batch Restaurants
    path('import-restaurants/', views.import_restaurants_index, name='import_restaurants_index'),
    path('import-restaurants/run/', views.run_import_restaurants, name='run_import_restaurants'),
    
    # Utilisateurs
    path('utilisateurs/', users_views.users_list, name='users_list'),
    path('utilisateurs/<str:uid>/refresh/', users_views.refresh_user_status, name='user_refresh_status'),
    path('utilisateurs/diagnostics/', users_views.users_diagnostics, name='users_diagnostics'),
    path('utilisateurs/log-all-premium/', users_views.users_log_all_premium, name='users_log_all_premium'),

    # CRUD Photos
    path('photos/', photos_views.photos_list, name='photos_list'),
    path('photos/<str:folder>/<str:photo_name>/', photos_views.photo_detail, name='photo_detail'),
    path('photos/<str:folder>/<str:photo_name>/url/', photos_views.photo_get_url, name='photo_get_url'),
    path('photos/upload/', photos_views.photo_upload, name='photo_upload'),
    path('photos/<str:folder>/<str:photo_name>/delete/', photos_views.photo_delete, name='photo_delete'),
    path('photos/<str:folder>/<str:photo_name>/rename/', photos_views.photo_rename, name='photo_rename'),
    path('photos/convert-png-to-webp/', photos_views.photo_convert_png_to_webp, name='photo_convert_png_to_webp'),
    path('photos/bulk-delete/', photos_views.photo_bulk_delete, name='photo_bulk_delete'),
    
    # Notifications
    path('notifications/', notifications_views.notifications_index, name='notifications_index'),
    path('notifications/send-all/', notifications_views.send_notification_to_all, name='send_notification_to_all'),
    path('notifications/send-all-prenom/', notifications_views.send_notification_to_all_with_prenom, name='send_notification_to_all_with_prenom'),
    path('notifications/send-group/', notifications_views.send_notification_to_group, name='send_notification_to_group'),
]


from django.urls import path
from . import views
from . import restaurants_views
from . import photos_views
from . import users_views
from . import notifications_views
from . import auth_views
from . import firebase_env_views
from . import search_restaurants_views
from . import guides_views
from . import announcements_views
from . import onboarding_views
from . import revenuecat_views

app_name = 'scripts_manager'

urlpatterns = [
    # Authentification
    path('login/', auth_views.login_view, name='login'),
    # path('register/', auth_views.register_view, name='register'),  # Inscription désactivée
    path('logout/', auth_views.logout_view, name='logout'),
    
    path('', views.index, name='index'),
    path('combien-tu-veux-augmenter-daniel/', views.augmenter_daniel, name='augmenter_daniel'),
    path('img-daniel-troll.jpg', views.serve_daniel_image, name='serve_daniel_image'),

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
    path('import-restaurants/dev/', views.dev_import_function, name='dev_import_function'),
    path('import-restaurants/logs/', views.get_import_logs, name='get_import_logs'),
    path('import-restaurants/download-logs/', views.download_import_logs, name='download_import_logs'),
    path('import-restaurants/analyze-sheets/', views.analyze_excel_sheets, name='analyze_excel_sheets'),
    
    # Restauration de Backups
    path('restore-backup/', views.restore_backup_index, name='restore_backup_index'),
    path('restore-backup/list/', views.list_backups, name='list_backups'),
    path('restore-backup/restore/', views.restore_backup, name='restore_backup'),
    
    # Utilisateurs
    path('utilisateurs/', users_views.users_list, name='users_list'),
    path('utilisateurs/dashboard/', revenuecat_views.dashboard_revenuecat, name='dashboard_revenuecat'),
    path('utilisateurs/dashboard/refresh/', revenuecat_views.refresh_all_revenuecat, name='refresh_all_revenuecat'),
    path('utilisateurs/dashboard/scan-status/', revenuecat_views.scan_status_api, name='rc_scan_status'),
    path('utilisateurs/<str:uid>/', users_views.user_detail, name='user_detail'),
    path('utilisateurs/<str:uid>/refresh-revenuecat/', revenuecat_views.user_refresh_revenuecat, name='user_refresh_revenuecat'),
    
    # Gestion environnement Firebase
    path('firebase-env/switch/', firebase_env_views.switch_firebase_env, name='switch_firebase_env'),
    path('firebase-env/status/', firebase_env_views.get_firebase_env, name='get_firebase_env'),

    # CRUD Photos
    path('photos/', photos_views.photos_list, name='photos_list'),
    path('photos/<str:folder>/<str:photo_name>/', photos_views.photo_detail, name='photo_detail'),
    path('photos/<str:folder>/<str:photo_name>/url/', photos_views.photo_get_url, name='photo_get_url'),
    path('photos/upload/', photos_views.photo_upload, name='photo_upload'),
    path('photos/<str:folder>/<str:photo_name>/delete/', photos_views.photo_delete, name='photo_delete'),
    path('photos/<str:folder>/<str:photo_name>/rename/', photos_views.photo_rename, name='photo_rename'),
    path('photos/convert-png-to-webp/', photos_views.photo_convert_png_to_webp, name='photo_convert_png_to_webp'),
    path('photos/bulk-delete/', photos_views.photo_bulk_delete, name='photo_bulk_delete'),
    path('photos/export-restaurants-sans-photo-webp/', photos_views.photo_export_restaurants_without_webp, name='photo_export_restaurants_without_webp'),
    
    # Notifications
    path('notifications/', notifications_views.notifications_index, name='notifications_index'),
    path('notifications/send-all/', notifications_views.send_notification_to_all, name='send_notification_to_all'),
    path('notifications/send-all-prenom/', notifications_views.send_notification_to_all_with_prenom, name='send_notification_to_all_with_prenom'),
    path('notifications/send-group/', notifications_views.send_notification_to_group, name='send_notification_to_group'),
    
    # Annonces (Événements + Sondages)
    path('announcements/', announcements_views.announcements_list, name='announcements_list'),
    path('announcements/create/', announcements_views.announcement_create, name='announcement_create'),
    path('announcements/list-storage-images/', announcements_views.list_storage_images, name='list_storage_images'),
    path('announcements/upload-image/', announcements_views.announcement_upload_image, name='announcement_upload_image'),
    path('announcements/<str:announcement_id>/', announcements_views.announcement_detail, name='announcement_detail'),
    path('announcements/<str:announcement_id>/edit/', announcements_views.announcement_edit, name='announcement_edit'),
    path('announcements/<str:announcement_id>/delete/', announcements_views.announcement_delete, name='announcement_delete'),
    path('announcements/<str:announcement_id>/json/', announcements_views.announcement_get_json, name='announcement_get_json'),
    path('announcements/<str:announcement_id>/export/', announcements_views.poll_export_answers, name='poll_export_answers'),

    # Guides
    path('guides/', guides_views.guides_list, name='guides_list'),
    path('guides/create/', guides_views.guide_create, name='guide_create'),
    path('guides/import/', guides_views.guides_import_csv, name='guides_import_csv'),
    path('guides/<str:guide_id>/', guides_views.guide_detail, name='guide_detail'),
    path('guides/<str:guide_id>/edit/', guides_views.guide_edit, name='guide_edit'),
    path('guides/<str:guide_id>/delete/', guides_views.guide_delete, name='guide_delete'),
    path('guides/<str:guide_id>/json/', guides_views.guide_get_json, name='guide_get_json'),

    # Onboarding Restaurants
    path('onboarding-restaurants/', onboarding_views.onboarding_list, name='onboarding_list'),
    path('onboarding-restaurants/import/', onboarding_views.onboarding_import, name='onboarding_import'),
    path('onboarding-restaurants/import/confirm/', onboarding_views.onboarding_import_confirm, name='onboarding_import_confirm'),
    path('onboarding-restaurants/<str:restaurant_id>/', onboarding_views.onboarding_detail, name='onboarding_detail'),
    path('onboarding-restaurants/<str:restaurant_id>/delete/', onboarding_views.onboarding_delete, name='onboarding_delete'),

    # Recherche de restaurants
    path('search/', search_restaurants_views.search_restaurants_index, name='search_restaurants'),
    path('search/analyze-columns/', search_restaurants_views.analyze_excel_columns, name='analyze_excel_columns'),
    path('search/run/', search_restaurants_views.run_search_restaurants, name='run_search_restaurants'),
    path('search/logs/', search_restaurants_views.get_search_logs, name='get_search_logs'),
    path('search/download/', search_restaurants_views.download_search_result, name='download_search_result'),
    path('search/download-logs/', search_restaurants_views.download_search_logs, name='download_search_logs'),
]


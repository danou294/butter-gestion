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
from . import quick_filters_views
from . import signups_views
from . import coups_de_coeur_views
from . import recommended_views
from . import home_guide_views
from . import marrakech_views
from . import videos_views
from . import home_sections_views
from . import paywall_config_views
from . import survey_views
from . import paywall_offerings_views

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
    path('import-restaurants/example-csv/<str:variant>/', views.download_example_csv, name='download_example_csv'),
    path('import-restaurants/parse-list/', views.parse_restaurant_list_file, name='parse_restaurant_list_file'),
    
    # Restauration de Backups
    path('restore-backup/', views.restore_backup_index, name='restore_backup_index'),
    path('restore-backup/list/', views.list_backups, name='list_backups'),
    path('restore-backup/restore/', views.restore_backup, name='restore_backup'),
    
    # Utilisateurs
    path('utilisateurs/', users_views.users_list, name='users_list'),
    path('utilisateurs/dashboard/', revenuecat_views.dashboard_revenuecat, name='dashboard_revenuecat'),
    path('utilisateurs/dashboard/refresh/', revenuecat_views.refresh_all_revenuecat, name='refresh_all_revenuecat'),
    path('utilisateurs/dashboard/scan-status/', revenuecat_views.scan_status_api, name='rc_scan_status'),
    path('utilisateurs/abonnes/', revenuecat_views.subscribers_list, name='subscribers_list'),
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
    path('guides/export/', guides_views.guides_export, name='guides_export'),
    path('guides/<str:guide_id>/', guides_views.guide_detail, name='guide_detail'),
    path('guides/<str:guide_id>/edit/', guides_views.guide_edit, name='guide_edit'),
    path('guides/<str:guide_id>/delete/', guides_views.guide_delete, name='guide_delete'),
    path('guides/<str:guide_id>/json/', guides_views.guide_get_json, name='guide_get_json'),

    # Onboarding Restaurants
    path('onboarding-restaurants/', onboarding_views.onboarding_list, name='onboarding_list'),
    path('onboarding-restaurants/import/', onboarding_views.onboarding_import, name='onboarding_import'),
    path('onboarding-restaurants/import/confirm/', onboarding_views.onboarding_import_confirm, name='onboarding_import_confirm'),
    path('onboarding-restaurants/export/', onboarding_views.onboarding_export, name='onboarding_export'),
    path('onboarding-restaurants/<str:restaurant_id>/', onboarding_views.onboarding_detail, name='onboarding_detail'),
    path('onboarding-restaurants/<str:restaurant_id>/delete/', onboarding_views.onboarding_delete, name='onboarding_delete'),

    # Dashboard unifié (inscriptions + RevenueCat)
    path('dashboard/', signups_views.dashboard, name='dashboard'),

    # Quick Filters
    path('quick-filters/', quick_filters_views.quick_filters_list, name='quick_filters_list'),
    path('quick-filters/create/', quick_filters_views.quick_filter_create, name='quick_filter_create'),
    path('quick-filters/<str:filter_id>/edit/', quick_filters_views.quick_filter_edit, name='quick_filter_edit'),
    path('quick-filters/<str:filter_id>/delete/', quick_filters_views.quick_filter_delete, name='quick_filter_delete'),
    path('quick-filters/<str:filter_id>/json/', quick_filters_views.quick_filter_get_json, name='quick_filter_get_json'),

    # Coups de coeur de la semaine
    path('coups-de-coeur/', coups_de_coeur_views.coups_de_coeur_manage, name='coups_de_coeur_manage'),
    path('coups-de-coeur/save/', coups_de_coeur_views.coups_de_coeur_save, name='coups_de_coeur_save'),
    path('coups-de-coeur/export/', coups_de_coeur_views.coups_de_coeur_export, name='coups_de_coeur_export'),

    # Recommandés pour toi
    path('recommandes/', recommended_views.recommended_manage, name='recommended_manage'),
    path('recommandes/save/', recommended_views.recommended_save, name='recommended_save'),
    path('recommandes/export/', recommended_views.recommended_export, name='recommended_export'),

    # Guide de la page d'accueil
    path('home-guide/', home_guide_views.home_guide_manage, name='home_guide_manage'),
    path('home-guide/save/', home_guide_views.home_guide_save, name='home_guide_save'),

    # Sections dynamiques de la Home
    path('home-sections/', home_sections_views.home_sections_manage, name='home_sections_manage'),
    path('home-sections/save/', home_sections_views.home_sections_save, name='home_sections_save'),
    path('home-sections/<str:section_id>/delete/', home_sections_views.home_sections_delete, name='home_sections_delete'),
    path('home-sections/seed-types/', home_sections_views.home_sections_seed_types, name='home_sections_seed_types'),
    path('home-sections/order/', home_sections_views.home_sections_order, name='home_sections_order'),
    path('home-sections/order/save/', home_sections_views.home_sections_order_save, name='home_sections_order_save'),

    # Sondages in-app
    path('surveys/', survey_views.survey_list, name='survey_list'),
    path('surveys/create/', survey_views.survey_edit, name='survey_create'),
    path('surveys/save/', survey_views.survey_save, name='survey_save'),
    path('surveys/seed/', survey_views.survey_seed, name='survey_seed'),
    path('surveys/<str:survey_id>/edit/', survey_views.survey_edit, name='survey_edit'),
    path('surveys/<str:survey_id>/delete/', survey_views.survey_delete, name='survey_delete'),
    path('surveys/<str:survey_id>/results/', survey_views.survey_results, name='survey_results'),
    path('surveys/<str:survey_id>/export-csv/', survey_views.survey_export_csv, name='survey_export_csv'),

    # Paywall Config
    path('paywall-config/', paywall_config_views.paywall_config_manage, name='paywall_config_manage'),
    path('paywall-config/save/', paywall_config_views.paywall_config_save, name='paywall_config_save'),
    path('paywall-config/reset/', paywall_config_views.paywall_config_reset, name='paywall_config_reset'),

    # Paywall Offerings
    path('paywall-offerings/', paywall_offerings_views.paywall_offerings_manage, name='paywall_offerings_manage'),
    path('paywall-offerings/save/', paywall_offerings_views.paywall_offerings_save, name='paywall_offerings_save'),
    path('paywall-offerings/reset/', paywall_offerings_views.paywall_offerings_reset, name='paywall_offerings_reset'),

    # Recherche de restaurants
    path('search/', search_restaurants_views.search_restaurants_index, name='search_restaurants'),
    path('search/analyze-columns/', search_restaurants_views.analyze_excel_columns, name='analyze_excel_columns'),
    path('search/run/', search_restaurants_views.run_search_restaurants, name='run_search_restaurants'),
    path('search/logs/', search_restaurants_views.get_search_logs, name='get_search_logs'),
    path('search/download/', search_restaurants_views.download_search_result, name='download_search_result'),
    path('search/download-logs/', search_restaurants_views.download_search_logs, name='download_search_logs'),

    # Vidéos (Butter Reels)
    path('videos/', videos_views.videos_list, name='videos_list'),
    path('videos/upload/', videos_views.video_upload, name='video_upload'),
    path('videos/bulk-upload/', videos_views.video_bulk_upload, name='video_bulk_upload'),
    path('videos/bulk-upload/api/', videos_views.video_bulk_upload_api, name='video_bulk_upload_api'),
    path('videos/<str:video_id>/', videos_views.video_detail, name='video_detail'),
    path('videos/<str:video_id>/edit/', videos_views.video_edit, name='video_edit'),
    path('videos/<str:video_id>/delete/', videos_views.video_delete, name='video_delete'),
    path('videos/<str:video_id>/toggle-active/', videos_views.video_toggle_active, name='video_toggle_active'),
    path('videos/<str:video_id>/json/', videos_views.video_get_json, name='video_get_json'),
    path('videos/<str:video_id>/comments/<str:comment_id>/delete/', videos_views.video_delete_comment, name='video_delete_comment'),

    # Marrakech
    path('marrakech/', marrakech_views.marrakech_list, name='marrakech_list'),
    path('marrakech/export/', marrakech_views.marrakech_export, name='marrakech_export'),
    path('marrakech/stats/', marrakech_views.marrakech_stats, name='marrakech_stats'),
    path('marrakech/<str:doc_id>/', marrakech_views.marrakech_detail, name='marrakech_detail'),
]


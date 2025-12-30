from django.db import models
import json


class RevenueCatUserStatus(models.Model):
    """
    Modèle pour stocker l'historique des statuts RevenueCat des utilisateurs
    """
    uid = models.CharField(max_length=255, db_index=True, help_text="UID Firebase de l'utilisateur")
    phone = models.CharField(max_length=50, db_index=True, help_text="Numéro de téléphone (hashé pour RevenueCat)")
    app_user_id = models.CharField(max_length=255, db_index=True, help_text="App User ID RevenueCat (hash du téléphone)")
    
    # Statut actuel
    status = models.CharField(max_length=20, choices=[
        ('active', 'Premium actif'),
        ('trial', 'Essai en cours'),
        ('grace', 'Grace period'),
        ('expired', 'Abonnement expiré'),
        ('none', 'Gratuit'),
    ], default='none')
    status_label = models.CharField(max_length=100)
    
    # Informations d'abonnement
    is_active = models.BooleanField(default=False)
    is_sandbox = models.BooleanField(default=False)
    is_sandbox_entitlement = models.BooleanField(default=False)
    is_sandbox_subscription = models.BooleanField(null=True, blank=True)
    
    product_identifier = models.CharField(max_length=255, null=True, blank=True)
    period_type = models.CharField(max_length=50, null=True, blank=True)
    will_renew = models.BooleanField(default=False)
    
    # Dates
    expires_at = models.DateTimeField(null=True, blank=True)
    purchase_date = models.DateTimeField(null=True, blank=True)
    grace_period_expires_at = models.DateTimeField(null=True, blank=True)
    
    # Données brutes (JSON)
    raw_data = models.JSONField(default=dict, help_text="Données brutes complètes de l'API RevenueCat")
    
    # Métadonnées
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'revenuecat_user_status'
        indexes = [
            models.Index(fields=['uid', '-created_at']),
            models.Index(fields=['phone', '-created_at']),
            models.Index(fields=['status', '-created_at']),
        ]
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.uid} - {self.status} ({self.created_at})"


class RevenueCatHistory(models.Model):
    """
    Modèle pour stocker l'historique quotidien des statuts RevenueCat
    Un enregistrement par jour par utilisateur
    """
    uid = models.CharField(max_length=255, db_index=True)
    phone = models.CharField(max_length=50, db_index=True)
    app_user_id = models.CharField(max_length=255, db_index=True)
    
    # Date du snapshot
    snapshot_date = models.DateField(db_index=True)
    
    # Statut du jour
    status = models.CharField(max_length=20, choices=[
        ('active', 'Premium actif'),
        ('trial', 'Essai en cours'),
        ('grace', 'Grace period'),
        ('expired', 'Abonnement expiré'),
        ('none', 'Gratuit'),
    ], default='none')
    
    is_active = models.BooleanField(default=False)
    is_sandbox = models.BooleanField(default=False)
    product_identifier = models.CharField(max_length=255, null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'revenuecat_history'
        unique_together = [['uid', 'snapshot_date']]
        indexes = [
            models.Index(fields=['uid', '-snapshot_date']),
            models.Index(fields=['snapshot_date']),
        ]
        ordering = ['-snapshot_date']
    
    def __str__(self):
        return f"{self.uid} - {self.status} ({self.snapshot_date})"

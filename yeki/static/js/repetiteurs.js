// static/js/repetiteurs.js

// Navigation scroll effect
window.addEventListener('scroll', function() {
  const navbar = document.getElementById('navbar');
  if (window.scrollY > 50) {
    navbar.classList.add('scrolled');
  } else {
    navbar.classList.remove('scrolled');
  }
});

// Mobile menu toggle
const burger = document.getElementById('burger');
const mobileMenu = document.getElementById('mobileMenu');
burger.addEventListener('click', () => {
  mobileMenu.classList.toggle('open');
});

// Close mobile menu on link click
document.querySelectorAll('#mobileMenu a').forEach(link => {
  link.addEventListener('click', () => {
    mobileMenu.classList.remove('open');
  });
});

// API Configuration
const API_BASE_URL = 'https://yeki.pythonanywhere.com/api';

// Éléments DOM
const searchInput = document.getElementById('searchInput');
const niveauInput = document.getElementById('niveauInput');
const villeInput = document.getElementById('villeInput');
const searchBtn = document.getElementById('searchBtn');
const resultsGrid = document.getElementById('resultsGrid');
const resultsHeader = document.getElementById('resultsHeader');
const resultsCount = document.getElementById('resultsCount');
const loadingState = document.getElementById('loadingState');
const emptyState = document.getElementById('emptyState');

// Récupérer le token depuis localStorage ou cookies
function getToken() {
  const token = localStorage.getItem('token');
  if (token) return token;
  const cookies = document.cookie.split(';');
  for (let cookie of cookies) {
    const [name, value] = cookie.trim().split('=');
    if (name === 'token') return value;
  }
  return null;
}

// Récupérer les paramètres de recherche
function getSearchParams() {
  return {
    ville: villeInput?.value || '',
    niveau: niveauInput?.value || ''
  };
}

// Rechercher les répétiteurs
async function rechercherRepetiteurs(matiere) {
  if (!matiere || matiere.trim() === '') {
    showMessage('Veuillez entrer une matière', 'warning');
    return;
  }

  // Afficher le chargement
  loadingState.style.display = 'block';
  resultsHeader.style.display = 'none';
  emptyState.style.display = 'none';
  resultsGrid.innerHTML = '';

  const token = getToken();
  const headers = {
    'Content-Type': 'application/json',
  };
  if (token) {
    headers['Authorization'] = `Token ${token}`;
  }

  try {
    // Construire l'URL avec les paramètres
    let url = `${API_BASE_URL}/repetiteurs/search/?matiere=${encodeURIComponent(matiere)}`;
    
    const params = getSearchParams();
    if (params.ville && params.ville.trim()) {
      url += `&ville=${encodeURIComponent(params.ville.trim())}`;
    }
    if (params.niveau && params.niveau.trim()) {
      url += `&niveau=${encodeURIComponent(params.niveau.trim())}`;
    }

    console.log('URL de recherche:', url);

    const response = await fetch(url, {
      method: 'GET',
      headers: headers,
    });

    if (response.ok) {
      const data = await response.json();
      afficherResultats(data, matiere);
    } else {
      const errorData = await response.json().catch(() => ({}));
      emptyState.style.display = 'block';
      emptyState.innerHTML = `
        <i class="fas fa-exclamation-triangle"></i>
        <p>Erreur ${response.status}: ${errorData.message || response.statusText}</p>
        <p style="font-size: 0.8rem; margin-top: 8px;">Veuillez vous reconnecter.</p>
        <button onclick="window.location.href='/web-login/'" style="margin-top: 16px; padding: 8px 24px; background: #2884a0; color: white; border: none; border-radius: 8px; cursor: pointer;">
          Se connecter
        </button>
      `;
    }
  } catch (error) {
    console.error('Erreur:', error);
    emptyState.style.display = 'block';
    emptyState.innerHTML = `
      <i class="fas fa-wifi"></i>
      <p>Erreur de connexion au serveur</p>
      <p style="font-size: 0.8rem; margin-top: 8px;">Vérifiez votre connexion internet.</p>
    `;
  } finally {
    loadingState.style.display = 'none';
  }
}

// Afficher les résultats
function afficherResultats(data, matiere) {
  const repetiteurs = data.repetiteurs || [];
  
  if (repetiteurs.length === 0) {
    emptyState.style.display = 'block';
    resultsHeader.style.display = 'none';
    return;
  }

  resultsHeader.style.display = 'flex';
  resultsCount.textContent = `${repetiteurs.length} répétiteur${repetiteurs.length > 1 ? 's' : ''} trouvé${repetiteurs.length > 1 ? 's' : ''} pour "${matiere}"`;
  
  resultsGrid.innerHTML = repetiteurs.map(rep => {
    // Vérifier si le numéro WhatsApp est valide
    const hasWhatsApp = rep.whatsapp && rep.whatsapp.trim() !== '';
    const cleanNumber = hasWhatsApp ? cleanPhoneNumber(rep.whatsapp) : '';
    
    return `
      <div class="repetiteur-card">
        <div class="card-header">
          <div class="avatar">${getInitials(rep.nom)}</div>
          <div>
            <h3>${escapeHtml(rep.nom)}</h3>
            <p>@${escapeHtml(rep.username)}</p>
            ${rep.ville ? `<p style="font-size: 0.7rem; color: #64748b;"><i class="fas fa-map-marker-alt"></i> ${escapeHtml(rep.ville)}</p>` : ''}
          </div>
        </div>
        <div class="matiere-badge">
          <i class="fas fa-graduation-cap"></i> ${escapeHtml(rep.matiere)}
        </div>
        ${rep.matieres && rep.matieres.length > 1 ? `
          <div style="margin-bottom: 10px; font-size: 0.7rem; color: #64748b;">
            <i class="fas fa-book"></i> ${rep.matieres.join(', ')}
          </div>
        ` : ''}
        <div class="prix">
          <i class="fas fa-tag"></i> ${rep.tarif || 5000} FCFA/mois
        </div>
        ${hasWhatsApp ? `
          <button class="btn-whatsapp" onclick="contacterWhatsApp('${cleanNumber}', '${escapeHtml(rep.nom)}', '${escapeHtml(rep.matiere)}'); return false;">
            <i class="fab fa-whatsapp"></i> Contacter sur WhatsApp
          </button>
        ` : `
          <div class="btn-whatsapp disabled">
            <i class="fas fa-phone-slash"></i> Numéro non disponible
          </div>
        `}
      </div>
    `;
  }).join('');
}

// Nettoyer le numéro de téléphone
function cleanPhoneNumber(numero) {
  if (!numero) return '';
  let clean = numero.replace(/[^0-9+]/g, '');
  // Ajouter l'indicatif Cameroun si nécessaire
  if (!clean.startsWith('+237') && clean.startsWith('6') && clean.length === 9) {
    clean = '+237' + clean;
  }
  return clean;
}

// Contacter via WhatsApp
function contacterWhatsApp(numero, nom, matiere) {
  if (!numero || numero.trim() === '') {
    showMessage('Numéro WhatsApp non disponible', 'error');
    return;
  }

  const niveau = niveauInput?.value?.trim() || 'votre niveau';
  const ville = villeInput?.value?.trim() || 'votre ville';
  
  const message = encodeURIComponent(
    `Bonjour ${nom},\n\n` +
    `Je souhaite prendre des cours particuliers en ${matiere} avec vous via Yéki.\n` +
    `Niveau : ${niveau}\n` +
    `Ville : ${ville}\n` +
    `Tarif : 5000 FCFA/mois.\n\n` +
    `Pouvez-vous me donner plus d'informations sur vos disponibilités ?\n\n` +
    `Cordialement.`
  );
  
  const url = `https://wa.me/${numero}?text=${message}`;
  window.open(url, '_blank');
}

// Helper: Initiales
function getInitials(nom) {
  if (!nom) return '?';
  const parts = nom.trim().split(' ');
  if (parts.length >= 2) {
    return (parts[0][0] + parts[1][0]).toUpperCase();
  }
  return nom[0].toUpperCase();
}

// Helper: Échapper HTML
function escapeHtml(text) {
  if (!text) return '';
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

// Afficher un message
function showMessage(message, type = 'info') {
  const existing = document.querySelector('.toast-message');
  if (existing) existing.remove();
  
  const toast = document.createElement('div');
  toast.className = 'toast-message';
  toast.style.cssText = `
    position: fixed;
    top: 20px;
    left: 50%;
    transform: translateX(-50%);
    padding: 12px 24px;
    border-radius: 8px;
    color: white;
    font-weight: 500;
    z-index: 1000;
    animation: slideDown 0.3s ease;
    max-width: 90%;
    text-align: center;
    background: ${type === 'error' ? '#dc2626' : type === 'warning' ? '#f59e0b' : '#2884a0'};
  `;
  toast.textContent = message;
  document.body.appendChild(toast);
  
  setTimeout(() => {
    toast.style.opacity = '0';
    setTimeout(() => toast.remove(), 300);
  }, 3000);
}

// Ajouter le style pour l'animation
const style = document.createElement('style');
style.textContent = `
  @keyframes slideDown {
    from { opacity: 0; transform: translateX(-50%) translateY(-20px); }
    to { opacity: 1; transform: translateX(-50%) translateY(0); }
  }
`;
document.head.appendChild(style);

// Charger les préférences utilisateur
async function chargerPreferences() {
  const token = getToken();
  if (!token) return;
  
  try {
    const response = await fetch(`${API_BASE_URL}/users/profil/me/`, {
      headers: { 'Authorization': `Token ${token}` }
    });
    
    if (response.ok) {
      const data = await response.json();
      if (data.niveau) niveauInput.value = data.niveau;
      if (data.ville) villeInput.value = data.ville;
    }
  } catch (error) {
    console.error('Erreur lors du chargement des préférences:', error);
  }
}

// Événements
document.addEventListener('DOMContentLoaded', function() {
  // Charger les préférences utilisateur
  chargerPreferences();
  
  // Événements de recherche
  searchBtn.addEventListener('click', () => {
    const matiere = searchInput.value.trim();
    if (matiere) {
      rechercherRepetiteurs(matiere);
    } else {
      showMessage('Veuillez entrer une matière', 'warning');
    }
  });

  searchInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') {
      const matiere = searchInput.value.trim();
      if (matiere) {
        rechercherRepetiteurs(matiere);
      }
    }
  });

  niveauInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') {
      const matiere = searchInput.value.trim();
      if (matiere) {
        rechercherRepetiteurs(matiere);
      }
    }
  });

  villeInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') {
      const matiere = searchInput.value.trim();
      if (matiere) {
        rechercherRepetiteurs(matiere);
      }
    }
  });

  // Matières populaires
  document.querySelectorAll('.matiere-chip').forEach(chip => {
    chip.addEventListener('click', () => {
      const matiere = chip.getAttribute('data-matiere');
      if (matiere) {
        searchInput.value = matiere;
        rechercherRepetiteurs(matiere);
      }
    });
  });
});

// Téléchargement APK - détection de plateforme
function detectPlatform() {
  const userAgent = navigator.userAgent || navigator.vendor || window.opera;
  const isAndroid = /android/i.test(userAgent);
  return isAndroid;
}

if (detectPlatform()) {
  const apkUrl = "/static/app/yeki-v.1.0.3.apk";
  document.querySelectorAll('#downloadBtn, #mobileDownloadBtn').forEach(btn => {
    if (btn) btn.href = apkUrl;
  });
}
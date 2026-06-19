// static/js/repetiteurs.js

// Navigation scroll effect (identique à landing-page)
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
const searchBtn = document.getElementById('searchBtn');
const resultsGrid = document.getElementById('resultsGrid');
const resultsHeader = document.getElementById('resultsHeader');
const resultsCount = document.getElementById('resultsCount');
const loadingState = document.getElementById('loadingState');
const emptyState = document.getElementById('emptyState');

// Récupérer le token depuis localStorage
function getToken() {
  const token = localStorage.getItem('token');
  if (token) return token;
  // Essayer de récupérer depuis les cookies
  const cookies = document.cookie.split(';');
  for (let cookie of cookies) {
    const [name, value] = cookie.trim().split('=');
    if (name === 'token') return value;
  }
  return null;
}

// Récupérer les paramètres de recherche
function getSearchParams() {
  // Récupérer depuis les champs de formulaire
  const ville = document.querySelector('#villeInput')?.value || '';
  const niveau = document.querySelector('#niveauInput')?.value || '';
  return { ville, niveau };
}

// Rechercher les répétiteurs
async function rechercherRepetiteurs(matiere) {
  if (!matiere || matiere.trim() === '') {
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
    
    // Ajouter les paramètres supplémentaires
    const params = getSearchParams();
    if (params.ville) {
      url += `&ville=${encodeURIComponent(params.ville)}`;
    }
    if (params.niveau) {
      url += `&niveau=${encodeURIComponent(params.niveau)}`;
    }

    const response = await fetch(url, {
      method: 'GET',
      headers: headers,
    });

    if (response.ok) {
      const data = await response.json();
      afficherResultats(data, matiere);
    } else {
      // En cas d'erreur, afficher un message
      emptyState.style.display = 'block';
      emptyState.innerHTML = `
        <i class="fas fa-exclamation-triangle"></i>
        <p>Erreur ${response.status}: ${response.statusText}</p>
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
  
  resultsGrid.innerHTML = repetiteurs.map(rep => `
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
        <i class="fas fa-tag"></i> ${rep.tarif} FCFA/mois
      </div>
      <a href="#" class="btn-whatsapp" onclick="contacterWhatsApp('${rep.whatsapp}', '${escapeHtml(rep.nom)}', '${escapeHtml(rep.matiere)}'); return false;">
        <i class="fab fa-whatsapp"></i> Contacter sur WhatsApp
      </a>
    </div>
  `).join('');
}

// Contacter via WhatsApp
function contacterWhatsApp(numero, nom, matiere) {
  // Nettoyer le numéro
  let cleanNumber = numero.replace(/[^0-9+]/g, '');
  if (!cleanNumber.startsWith('+237') && cleanNumber.startsWith('6')) {
    cleanNumber = '+237' + cleanNumber;
  }
  
  // Récupérer le niveau et la ville depuis les champs
  const niveau = document.querySelector('#niveauInput')?.value || 'votre niveau';
  const ville = document.querySelector('#villeInput')?.value || 'votre ville';
  
  const message = encodeURIComponent(
    `Bonjour ${nom},\n\n` +
    `Je souhaite prendre des cours particuliers en ${matiere} avec vous via Yéki.\n` +
    `Niveau : ${niveau}\n` +
    `Ville : ${ville}\n` +
    `Tarif : 5000 FCFA/mois.\n\n` +
    `Pouvez-vous me donner plus d'informations sur vos disponibilités ?\n\n` +
    `Cordialement.`
  );
  
  window.open(`https://wa.me/${cleanNumber}?text=${message}`, '_blank');
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

// Ajouter des champs de formulaire pour niveau et ville
function addExtraFields() {
  const searchSection = document.querySelector('.search-section');
  const searchBox = document.querySelector('.search-box');
  
  if (searchBox && !document.querySelector('#extraFields')) {
    const extraDiv = document.createElement('div');
    extraDiv.id = 'extraFields';
    extraDiv.style.cssText = 'display: flex; gap: 10px; margin-top: 12px; flex-wrap: wrap;';
    extraDiv.innerHTML = `
      <input type="text" id="niveauInput" class="search-input" placeholder="Niveau (ex: Terminale)" style="flex: 1; min-width: 120px; padding: 10px 16px; border: 2px solid #e2e8f0; border-radius: 12px; font-size: 0.9rem;">
      <input type="text" id="villeInput" class="search-input" placeholder="Ville (ex: Yaoundé)" style="flex: 1; min-width: 120px; padding: 10px 16px; border: 2px solid #e2e8f0; border-radius: 12px; font-size: 0.9rem;">
    `;
    searchBox.parentNode.insertBefore(extraDiv, searchBox.nextSibling);
  }
}

// Événements
document.addEventListener('DOMContentLoaded', function() {
  // Ajouter les champs supplémentaires
  addExtraFields();
  
  // Événements de recherche
  searchBtn.addEventListener('click', () => {
    const matiere = searchInput.value.trim();
    if (matiere) {
      rechercherRepetiteurs(matiere);
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
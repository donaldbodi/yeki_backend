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
const searchBtn = document.getElementById('searchBtn');
const resultsGrid = document.getElementById('resultsGrid');
const resultsHeader = document.getElementById('resultsHeader');
const resultsCount = document.getElementById('resultsCount');
const loadingState = document.getElementById('loadingState');
const emptyState = document.getElementById('emptyState');

// Récupérer le token depuis le localStorage ou les cookies
function getToken() {
  // Essayer de récupérer depuis localStorage
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
    // Appel API
    const response = await fetch(`${API_BASE_URL}/repetiteurs/search/?matiere=${encodeURIComponent(matiere)}`, {
      method: 'GET',
      headers: headers,
    });

    if (response.ok) {
      const data = await response.json();
      afficherResultats(data, matiere);
    } else {
      // En cas d'erreur API, afficher des données de démonstration
      afficherResultatsDemo(matiere);
    }
  } catch (error) {
    console.error('Erreur:', error);
    afficherResultatsDemo(matiere);
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

// Données de démonstration (si l'API n'est pas encore disponible)
function afficherResultatsDemo(matiere) {
  const repetiteursDemo = [
    {
      nom: "M. Kamga François",
      username: "kamga_francois",
      matiere: matiere,
      matieres: [matiere],
      tarif: 5000,
      whatsapp: "237691234567",
      ville: "Yaoundé"
    },
    {
      nom: "Mme Ngo Mbarga",
      username: "ngo_mbarga",
      matiere: matiere,
      matieres: [matiere],
      tarif: 5000,
      whatsapp: "237698765432",
      ville: "Douala"
    },
    {
      nom: "M. Tchinda Pierre",
      username: "tchinda_pierre",
      matiere: matiere,
      matieres: [matiere],
      tarif: 5000,
      whatsapp: "237697654321",
      ville: "Yaoundé"
    }
  ];

  resultsHeader.style.display = 'flex';
  resultsCount.textContent = `${repetiteursDemo.length} répétiteur${repetiteursDemo.length > 1 ? 's' : ''} trouvé${repetiteursDemo.length > 1 ? 's' : ''} pour "${matiere}" (version démo)`;
  
  resultsGrid.innerHTML = repetiteursDemo.map(rep => `
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
  
  const message = encodeURIComponent(
    `Bonjour ${nom},\n\nJe souhaite prendre des cours particuliers en ${matiere} avec vous via Yéki.\nTarif : 5000 FCFA/mois.\n\nPouvez-vous me donner plus d'informations ?\n\nCordialement.`
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

// Événements
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
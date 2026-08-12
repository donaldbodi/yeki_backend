// static/js/script.js

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

// Counter animation
const counters = document.querySelectorAll('.counter');
const speed = 200;

counters.forEach(counter => {
  const updateCount = () => {
    const target = parseInt(counter.getAttribute('data-target'));
    const count = parseInt(counter.innerText);
    const increment = Math.ceil(target / speed);
    
    if (count < target) {
      counter.innerText = count + increment;
      setTimeout(updateCount, 20);
    } else {
      counter.innerText = target;
    }
  };
  updateCount();
});

// FAQ toggle
function toggleFaq(element) {
  const content = element.querySelector('.faq-content');
  const icon = element.querySelector('.fa-chevron-down');
  
  // Fermer tous les autres FAQ
  document.querySelectorAll('.faq-item').forEach(item => {
    if (item !== element && item.classList.contains('active')) {
      item.classList.remove('active');
      const otherContent = item.querySelector('.faq-content');
      const otherIcon = item.querySelector('.fa-chevron-down');
      if (otherContent) otherContent.style.maxHeight = '0';
      if (otherIcon) otherIcon.style.transform = 'rotate(0deg)';
    }
  });
  
  element.classList.toggle('active');
  
  if (element.classList.contains('active')) {
    content.style.maxHeight = content.scrollHeight + 'px';
    if (icon) icon.style.transform = 'rotate(180deg)';
  } else {
    content.style.maxHeight = '0';
    if (icon) icon.style.transform = 'rotate(0deg)';
  }
}

// Detect platform and show appropriate download button
function detectPlatform() {
  const userAgent = navigator.userAgent || navigator.vendor || window.opera;
  const isAndroid = /android/i.test(userAgent);
  const isIOS = /iPad|iPhone|iPod/.test(userAgent) && !window.MSStream;
  const isDesktop = /Windows|Mac|Linux/.test(userAgent) && !/Mobile/.test(userAgent);

  const androidBtns = document.querySelectorAll('#downloadBtn, #heroDownloadBtn, #downloadAndroidBtn, #mobileDownloadBtn');
  const iosBtn = document.getElementById('downloadIOSBtn');
  const desktopBtn = document.getElementById('downloadDesktopBtn');

  if (isAndroid) {
    androidBtns.forEach(btn => {
      if (btn) btn.style.display = 'inline-flex';
    });
    if (iosBtn) iosBtn.style.display = 'none';
    if (desktopBtn) desktopBtn.style.display = 'none';
  } else if (isIOS) {
    androidBtns.forEach(btn => {
      if (btn) btn.style.display = 'none';
    });
    if (iosBtn) iosBtn.style.display = 'inline-flex';
    if (desktopBtn) desktopBtn.style.display = 'none';
  } else if (isDesktop) {
    androidBtns.forEach(btn => {
      if (btn) btn.style.display = 'none';
    });
    if (iosBtn) iosBtn.style.display = 'none';
    if (desktopBtn) desktopBtn.style.display = 'inline-flex';
  } else {
    androidBtns.forEach(btn => {
      if (btn) btn.style.display = 'inline-flex';
    });
    if (iosBtn) iosBtn.style.display = 'none';
    if (desktopBtn) desktopBtn.style.display = 'none';
  }
}

// Backend réel (Railway) — l'ancienne URL PythonAnywhere pointait vers un
// hébergeur décommissionné cette session, l'appel échouait silencieusement
// (catch ci-dessous) et le badge de version restait figé sur son repli.
const API_BASE_URL = 'https://yekibackend-production.up.railway.app/api';

// Get latest version from API
async function getLatestVersion() {
  try {
    const response = await fetch(`${API_BASE_URL}/latest-version/`);
    const data = await response.json();
    const version = data.version_name || 'v1.0.3';
    document.querySelectorAll('#appVersion, #footerVersion').forEach(el => {
      if (el) el.textContent = version;
    });
  } catch (e) {
    console.log('Version check failed');
  }
}

// Set download links
function setDownloadLinks() {
  const apkUrl = '/static/app/yeki-v.1.0.3.apk';
  document.querySelectorAll('#downloadBtn, #heroDownloadBtn, #downloadAndroidBtn, #mobileDownloadBtn').forEach(btn => {
    if (btn) btn.href = apkUrl;
  });
}

// Bouton Desktop : aucun binaire Windows/macOS/Linux n'existe encore
// (bug corrigé — ce bouton était affiché aux visiteurs desktop SANS
// jamais recevoir de lien réel). Interroge le backend
// (`AppVersion`, platform=desktop) : si un vrai binaire y est un jour
// publié (`download_url` non vide), le bouton devient un vrai lien ;
// sinon il reste honnêtement marqué "(bientôt)", même traitement déjà
// appliqué au bouton iOS — jamais un lien mort silencieux.
async function setupDesktopButton() {
  const desktopBtn = document.getElementById('downloadDesktopBtn');
  if (!desktopBtn) return;
  try {
    const response = await fetch(`${API_BASE_URL}/latest-version/?platform=desktop`);
    const data = await response.json();
    if (data.download_url) {
      desktopBtn.href = data.download_url;
    } else {
      desktopBtn.innerHTML = '<i class="fab fa-windows"></i> Windows (bientôt)';
      desktopBtn.addEventListener('click', (e) => e.preventDefault());
    }
  } catch (e) {
    desktopBtn.innerHTML = '<i class="fab fa-windows"></i> Windows (bientôt)';
    desktopBtn.addEventListener('click', (e) => e.preventDefault());
  }
}

// Initialize
document.addEventListener('DOMContentLoaded', function() {
  detectPlatform();
  getLatestVersion();
  setDownloadLinks();
  setupDesktopButton();
});
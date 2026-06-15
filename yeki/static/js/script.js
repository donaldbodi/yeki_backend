
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
    const content = element.querySelector('div:last-child');
    const icon = element.querySelector('.fa-chevron-down');
    if (content.style.maxHeight && content.style.maxHeight !== '0px') {
      content.style.maxHeight = '0';
      icon.style.transform = 'rotate(0deg)';
    } else {
      content.style.maxHeight = content.scrollHeight + 'px';
      icon.style.transform = 'rotate(180deg)';
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
      androidBtns.forEach(btn => btn.style.display = 'inline-flex');
      if (iosBtn) iosBtn.style.display = 'none';
      if (desktopBtn) desktopBtn.style.display = 'none';
    } else if (isIOS) {
      androidBtns.forEach(btn => btn.style.display = 'none');
      if (iosBtn) iosBtn.style.display = 'inline-flex';
      if (desktopBtn) desktopBtn.style.display = 'none';
    } else if (isDesktop) {
      androidBtns.forEach(btn => btn.style.display = 'none');
      if (iosBtn) iosBtn.style.display = 'none';
      if (desktopBtn) desktopBtn.style.display = 'inline-flex';
    } else {
      androidBtns.forEach(btn => btn.style.display = 'inline-flex');
      if (iosBtn) iosBtn.style.display = 'none';
      if (desktopBtn) desktopBtn.style.display = 'none';
    }
  }

  // Get latest version from API
  async function getLatestVersion() {
    try {
      const response = await fetch('https://yeki.pythonanywhere.com/api/latest-version/');
      const data = await response.json();
      const version = data.version_name || 'v1.0.3';
      document.querySelectorAll('#appVersion, #footerVersion').forEach(el => {
        if (el) el.textContent = version;
      });
    } catch (e) {
      console.log('Version check failed');
    }
  }

  detectPlatform();
  getLatestVersion();

  // Set download links
  const apkUrl = "{% static 'app/yeki-v.1.0.3.apk' %}";
  document.querySelectorAll('#downloadBtn, #heroDownloadBtn, #downloadAndroidBtn, #mobileDownloadBtn').forEach(btn => {
    if (btn) btn.href = apkUrl;
  });
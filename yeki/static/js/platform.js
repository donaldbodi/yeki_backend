// static/js/platform.js

function detectPlatform() {
    const userAgent = navigator.userAgent || navigator.vendor || window.opera;
    const platform = {
        isAndroid: /android/i.test(userAgent),
        isIOS: /iPad|iPhone|iPod/.test(userAgent) && !window.MSStream,
        isWeb: true,
        isDesktop: /Windows|Mac|Linux/.test(userAgent) && !/Mobile/.test(userAgent)
    };

    const downloadBtn = document.getElementById('download-btn');
    const iosDownloadBtn = document.getElementById('ios-download-btn');
    const desktopDownloadBtn = document.getElementById('desktop-download-btn');
    const webLoginBtn = document.getElementById('web-login-btn');

    if (platform.isAndroid) {
        if (downloadBtn) downloadBtn.style.display = 'flex';
        if (iosDownloadBtn) iosDownloadBtn.style.display = 'none';
        if (desktopDownloadBtn) desktopDownloadBtn.style.display = 'none';
        downloadBtn.href = "{% static 'app/yeki-v.1.0.3.apk' %}";
    } else if (platform.isIOS) {
        if (downloadBtn) downloadBtn.style.display = 'none';
        if (iosDownloadBtn) iosDownloadBtn.style.display = 'flex';
        if (desktopDownloadBtn) desktopDownloadBtn.style.display = 'none';
        iosDownloadBtn.href = "https://apps.apple.com/app/idXXXXXX";
    } else if (platform.isDesktop) {
        if (downloadBtn) downloadBtn.style.display = 'none';
        if (iosDownloadBtn) iosDownloadBtn.style.display = 'none';
        if (desktopDownloadBtn) desktopDownloadBtn.style.display = 'flex';
        desktopDownloadBtn.href = "{% static 'app/yeki-setup.exe' %}";
    } else {
        if (downloadBtn) downloadBtn.style.display = 'flex';
        if (iosDownloadBtn) iosDownloadBtn.style.display = 'none';
        if (desktopDownloadBtn) desktopDownloadBtn.style.display = 'none';
    }

    if (webLoginBtn) {
        webLoginBtn.onclick = (e) => {
            e.preventDefault();
            window.location.href = '/web-login/';
        };
    }
}

document.addEventListener('DOMContentLoaded', detectPlatform);
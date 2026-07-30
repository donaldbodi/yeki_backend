"""
Throttling — CDC_BACKEND §2.5.

`ScopedRateThrottle.parse_rate` (DRF natif) n'accepte qu'une unité simple
sans multiplicateur ("3/min", "10/hour" — la durée vient uniquement du
premier caractère de la période). Le scope `otp` (`3/10min`, anti-abus de
l'envoi de code par email) utilise un multiplicateur ("10min") : DRF lit
`period[0]` sur la chaîne complète après le nombre de requêtes, obtient le
premier chiffre du multiplicateur ("1" de "10min") au lieu d'une unité, et
lève un `KeyError` non rattrapé — chaque appel à un endpoint avec ce scope
échouait donc en 500, jamais détecté faute de test avant P5.5 (voir
docs/ecarts/forgot_password.md).
"""

import re

from rest_framework.throttling import ScopedRateThrottle

_DUREES_PAR_UNITE = {"s": 1, "m": 60, "h": 3600, "d": 86400}

_RATE_AVEC_MULTIPLICATEUR = re.compile(r"^(\d*)([a-zA-Z]+)$")


class YekiScopedRateThrottle(ScopedRateThrottle):
    """`ScopedRateThrottle` tolérant un multiplicateur devant l'unité de
    durée (`"3/10min"` → 3 requêtes / 600 secondes)."""

    def parse_rate(self, rate):
        if rate is None:
            return (None, None)
        num, period = rate.split("/")
        num_requests = int(num)
        match = _RATE_AVEC_MULTIPLICATEUR.match(period)
        if not match:
            return super().parse_rate(rate)
        multiplicateur = int(match.group(1)) if match.group(1) else 1
        duration = _DUREES_PAR_UNITE[match.group(2)[0].lower()] * multiplicateur
        return (num_requests, duration)

"""
Tests de la commande `verifier_stockage_medias` — voir
docs/FIREBASE_STORAGE_SETUP.md. Le stockage cloud réel (Firebase
Storage) n'est jamais sollicité ici : `default_storage`/`requests.get`
sont simulés, seule la LOGIQUE de la commande (branches succès/échec,
messages renvoyant à la bonne étape du guide, nettoyage systématique)
est vérifiée.
"""

from unittest.mock import MagicMock, patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

_STORAGES_CLOUD = {
    "default": {"BACKEND": "storages.backends.gcloud.GoogleCloudStorage"},
    "staticfiles": {"BACKEND": "config.storage_backends.LenientManifestStaticFilesStorage"},
}


def test_backend_local_ne_verifie_rien(capsys):
    """FileSystemStorage actif (dev/tests) — aucune écriture cloud tentée."""
    call_command("verifier_stockage_medias")
    sortie = capsys.readouterr().out
    assert "Stockage local" in sortie


@override_settings(STORAGES=_STORAGES_CLOUD)
@patch("apps.core.management.commands.verifier_stockage_medias.requests.get")
@patch("apps.core.management.commands.verifier_stockage_medias.default_storage")
def test_ecriture_et_lecture_publique_ok(mock_storage, mock_get, capsys):
    mock_storage.save.return_value = "_verification_stockage/abc.txt"
    mock_storage.url.return_value = "https://storage.googleapis.com/bucket/abc.txt"
    mock_get.return_value = MagicMock(
        status_code=200, content=b"verification stockage medias yeki"
    )

    call_command("verifier_stockage_medias")

    mock_storage.save.assert_called_once()
    mock_get.assert_called_once_with(
        "https://storage.googleapis.com/bucket/abc.txt", timeout=15
    )
    mock_storage.delete.assert_called_once_with("_verification_stockage/abc.txt")
    sortie = capsys.readouterr().out
    assert "opérationnel" in sortie


@override_settings(STORAGES=_STORAGES_CLOUD)
@patch("apps.core.management.commands.verifier_stockage_medias.default_storage")
def test_echec_ecriture_pointe_vers_etape_5(mock_storage):
    mock_storage.save.side_effect = Exception("403 Forbidden")

    with pytest.raises(CommandError, match="ECRITURE"):
        call_command("verifier_stockage_medias")

    mock_storage.delete.assert_not_called()


@override_settings(STORAGES=_STORAGES_CLOUD)
@patch("apps.core.management.commands.verifier_stockage_medias.requests.get")
@patch("apps.core.management.commands.verifier_stockage_medias.default_storage")
def test_echec_lecture_publique_pointe_vers_etape_4_et_nettoie_quand_meme(
    mock_storage, mock_get
):
    mock_storage.save.return_value = "_verification_stockage/abc.txt"
    mock_storage.url.return_value = "https://storage.googleapis.com/bucket/abc.txt"
    mock_get.return_value = MagicMock(status_code=403, content=b"")

    with pytest.raises(CommandError, match="LECTURE PUBLIQUE"):
        call_command("verifier_stockage_medias")

    # Le fichier de test est nettoyé même si la vérification échoue —
    # ne pas laisser de déchets dans le bucket à chaque exécution ratée.
    mock_storage.delete.assert_called_once_with("_verification_stockage/abc.txt")

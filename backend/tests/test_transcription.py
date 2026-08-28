from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_upload_rejects_non_audio_file() -> None:
    response = client.post(
        "/api/transcription/upload",
        files={"file": ("notes.txt", b"not audio", "text/plain")},
    )

    assert response.status_code == 415
    assert response.json() == {"detail": "Unsupported audio file type."}


def test_upload_rejects_invalid_audio_content() -> None:
    response = client.post(
        "/api/transcription/upload",
        files={"file": ("meeting.wav", b"RIFF", "audio/wav")},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Audio file could not be decoded."}
